import os
import json
import re
import sys
import tkinter as tk

from NameMapping import Mapping as NameMapping
from ShipConsumableDataAnalyze import ShipConsumableDataAnalyze
from ShipHullDataAnalyze import ShipHullDataAnalyze


class ShipDataAnalyzer:
    # 将正则编译移出循环，提高效率
    PATTERNS = {
        "Hull": re.compile(r'([A-Z]+\d*)_Hull'),
        "Artillery": re.compile(r'([A-Z]+\d*)_Artillery'),
        "ATBA": re.compile(r'([A-Z]+\d*)_ATBA'),
        "Torpedoes": re.compile(r'([A-Z]+\d*)_Torpedoes'),
        "DiveBomber": re.compile(r'([A-Z]+\d*)_DiveBomber'),
        "Fighter": re.compile(r'([A-Z]+\d*)_Fighter'),
        "SkipBomber": re.compile(r'([A-Z]+\d*)_SkipBomber'),
        "TorpedoBomber": re.compile(r'([A-Z]+\d*)_TorpedoBomber'),
        "AirSupport": re.compile(r'([A-Z]+\d*)_AirSupport'),
        "AirDefense": re.compile(r'([A-Z]+\d*)_AirDefense'),
        "DepthChargeGuns": re.compile(r"([A-Z]+\d*)_DepthChargeGuns"),
    }
    PATTERNS_NEW = {
        "Hull": re.compile(r'([A-Z]\d*)_Hull'),
    }

    DEFAULTS = {
        "Hull": re.compile(r'HullDefault'),
        "Artillery": re.compile(r'ArtilleryDefault'),
        "Torpedoes": re.compile(r'TorpedoesDefault'),
        "ATBA": re.compile(r'ATBADefault'),
        "DiveBomber": re.compile(r'DiveBomberDefault'),
        "Fighter": re.compile(r'FighterDefault'),
        "SkipBomber": re.compile(r'SkipBomberDefault'),
        "TorpedoBomber": re.compile(r'TorpedoBomberDefault'),
        "AirSupport": re.compile(r'AirSupportDefault'),
        "AirDefense": re.compile(r'AirDefenseDefault'),
        "DepthChargeGuns": re.compile(r"DepthChargeGunsDefault"),
    }

    HP_PATTERNS = {
        "Artillery": re.compile(r'HP_[A-Z]GM_\d+'),
        "ATBA": re.compile(r'HP_([A-Z]GS)_\d+'),
        "AirDefense": re.compile(r'(HP_[A-Z]GA_\d+|Aura_\d+|(Far|Medium|Near)\d*(_Bubbles)?)'),
        "Torpedoes": re.compile(r'HP_[A-Z]GT_\d+'),
        "DepthChargeGuns": re.compile(r"HP_[A-Z]GB_\d+"),
    }

    # 初始化
    def __init__(self, log_func=None):
        # 使用脚本所在绝对路径，增加健壮性
        if getattr(sys, 'frozen', False):
            # 如果是打包后的 EXE 运行，sys.executable 是 EXE 的全路径
            # 我们取它的目录名
            self.base_dir = os.path.dirname(sys.executable)
        else:
            # 如果是源码运行
            self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.log_callback = log_func  # 核心：保存 UI 传入的日志函数
        self.ability_name_map = {}
        self.ship_name_mapping = {}
        self.rage_name_mapping = {}
        self.gun_name_mapping = {}
        self.ammo_name_mapping = {}
        self.plane_name_mapping = {}
        self._cached_mod_data = {}  # 显式定义缓存属性
        self.consumable_analyzer = ShipConsumableDataAnalyze(self.base_dir)

    def initialize_mapping(self):
        self.load_ability_map()
        self.load_name_mapping()
        self.load_rage_name_mapping()
        self.load_gun_name_mapping()
        self.load_ammo_name_mapping()
        self.load_plane_name_mapping()
        self._log("舰船解析器映射表已同步")

    # 日志
    def _log(self, message):
        """内部调用的日志工具"""
        if self.log_callback:
            self.log_callback(message)  # 如果有回调，发给 UI
        else:
            print(message)  # 否则打印到控制台

    # 加载映射表
    def reload_mappings(self):
        """
        供外部（MainUI）调用的重新初始化接口
        当 POToolkit 更新了 json 文件后，点击按钮即可刷新内存中的字典
        """
        self._log("正在重新加载本地化数据...")
        # 重新执行一遍所有的加载方法
        self.initialize_mapping()
        self._log("数据刷新完成。")

    def load_name_mapping(self):
        mapping_path = os.path.join(self.base_dir, "data", "ship_names.json")
        try:
            if os.path.exists(mapping_path):
                with open(mapping_path, 'r', encoding='utf-8') as f:
                    self.ship_name_mapping = json.load(f)
        except Exception as e:
            self._log(f"读取船名映射出错: {e}")

    def load_ability_map(self):
        file_path = os.path.join(self.base_dir, "data", "consumable_names.json")
        try:
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    raw_json = json.load(f)
                    self.ability_name_map = {k.upper(): v for k, v in raw_json.items()}
        except Exception as e:
            self._log(f"读取消耗品名映射出错: {e}")

    def load_rage_name_mapping(self):
        """加载从 .po 文件提取的战斗指令名称映射表"""
        mapping_path = os.path.join(self.base_dir, "data", "rage_mode_names.json")
        try:
            if os.path.exists(mapping_path):
                with open(mapping_path, 'r', encoding='utf-8') as f:
                    self.rage_name_mapping = json.load(f)
        except Exception as e:
            self._log(f"读取战斗指令名称映射出错: {e}")

    def load_gun_name_mapping(self):
        """加载由 POToolKit 生成的武器翻译字典"""
        # 注意：这里的路径要与 MainUI 生成的路径一致
        guns_json_path = os.path.join(self.base_dir, "data", "guns_names.json")
        if os.path.exists(guns_json_path):
            try:
                with open(guns_json_path, 'r', encoding='utf-8') as f:
                    self.gun_name_mapping = json.load(f)
            except Exception as e:
                self._log(f"加载武器翻译失败: {e}")

    def load_ammo_name_mapping(self):
        """加载由 POToolKit 生成的弹药翻译字典"""
        # 路径指向 POToolkit 生成的 ammo_names.json
        ammo_json_path = os.path.join(self.base_dir, "data", "ammo_names.json")
        if os.path.exists(ammo_json_path):
            try:
                with open(ammo_json_path, 'r', encoding='utf-8') as f:
                    self.ammo_name_mapping = json.load(f)
            except Exception as e:
                self._log(f"加载弹药翻译失败: {e}")

    def load_plane_name_mapping(self):
        plane_json_path = os.path.join(self.base_dir, "data", "plane_names.json")
        if os.path.exists(plane_json_path):
            try:
                with open(plane_json_path, 'r', encoding='utf-8') as f:
                    self.plane_name_mapping = json.load(f)
            except Exception as e:
                self._log(f"加载飞机翻译失败: {e}")

    def get_localized_weapon_name(self, raw_id):
        """
        增强版映射逻辑：
        1. 处理 IDS_ 前缀
        2. 强制转为大写匹配，防止大小写导致匹配失败
        """
        if not raw_id:
            return "Unknown"

        # 处理逻辑：去掉 IDS_ 并统一转为大写
        clean_id = raw_id.replace("IDS_", "").upper()

        # 1. 尝试直接在映射表中查找（假设 mapping 里的 key 也是大写）
        if clean_id in self.gun_name_mapping:
            return self.gun_name_mapping[clean_id]

        # 2. 如果映射表的 Key 保持了原始大小写，则遍历匹配
        for k, v in self.gun_name_mapping.items():
            if k.upper() == clean_id:
                return v

        # 3. 实在查不到返回原名
        return raw_id

    def get_localized_plane_name(self, raw_id):
        """
        专门针对飞机映射表 (plane_name_mapping) 的检索逻辑
        """
        if not raw_id:
            return "Unknown"

        # 1. 格式清洗：移除 IDS_ 前缀，统一转大写，剔除首尾空格
        clean_id = raw_id.replace("IDS_", "").upper().strip()

        # 确保映射表存在且是字典
        table = getattr(self, 'plane_name_mapping', {})
        if not table:
            if self._log:
                self._log("❌ 错误：plane_name_mapping 未加载或为空")
            return raw_id

        # 2. 快速匹配 (最推荐的方式，效率为 O(1))
        if clean_id in table:
            return table[clean_id]

        # 3. 模糊/大小写兼容匹配 (防止 Key 在 JSON 中不是全大写)
        for k, v in table.items():
            if k.upper() == clean_id:
                return v

        # 4. 如果没找到，记录到 UI 日志框，并返回原始 ID
        if self._log:
            self._log(f"🔎 飞机映射缺失: {raw_id}")

        return raw_id

    # 战斗指令
    def parse_rage_mode_advanced(self, rage_data, ship_index, current_species):
        info = []
        # 1. 标题识别逻辑：完全移除 descriptionIDS，仅基于 rageModeName
        raw_name_upper = str(rage_data.get("rageModeName", "Unknown")).upper()
        base_msgid = f"IDS_DOCK_RAGE_MODE_TITLE_{raw_name_upper}"

        # 优先级：基础 IDS 映射 > 原始名称
        display_name = self.rage_name_mapping.get(base_msgid, raw_name_upper)

        info.append(f"=== 战斗指令: {display_name} ===")

        # 2. 基础配置
        boost = rage_data.get("boostDuration", 0)
        info.append(f"  [基础属性]")
        info.append(f"    - 持续时间: {boost}s")
        info.append(f"    - 自动激活: {'是' if rage_data.get('isAutoUsage') else '否'}")
        info.append(f"    - 常驻生效: {'是' if rage_data.get('isModifierWorksAlways') else '否'}")

        # 3. 衰减逻辑
        delay = rage_data.get("decrementDelay", 0)
        if delay > 0:
            info.append(f"  [衰减逻辑]")
            info.append(f"    - 衰减倒计时: {delay}s")
            info.append(f"    - 衰减周期: {rage_data.get('decrementPeriod', 1)}s")
            info.append(f"    - 衰减数值: {rage_data.get('decrementCount', 0)}%")

        # 4. 机制拆解 (直接平铺 Activator 和 Action)
        # 寻找包含 Trigger 关键字的字典，但不再显示该 Key 本身
        for key, trigger in rage_data.items():
            if "Trigger" in key and isinstance(trigger, dict):
                # 拆解激活条件 (Activator)
                act = trigger.get("Activator", {})
                if act:
                    info.append(f"  [激活条件]")
                    info.append(f"    - 触发类型: {act.get('type', 'Unknown')}")
                    for k, v in act.items():
                        if k == "type":
                            continue
                        # --- 核心修改：精准匹配飞机 ID 键 ---
                        elif k == "subRibbons" and isinstance(v, list):
                            # 将 rid 转为字符串去匹配 map，如果找不到则显示 "未知勋带(ID)"
                            ribbon_names = []
                            for rid in v:
                                name = NameMapping.RIBBON_MAP.get(str(rid), f"未知勋带({rid})")
                                ribbon_names.append(name)

                            # 格式化输出： 勋带名称1, 勋带名称2 (原始ID列表)
                            info.append(f"    - {NameMapping.DETAIL_MAP.get(k, k)}: {', '.join(ribbon_names)}")
                        else:
                            unit = "m" if k == "radius" else ""
                            info.append(f"    - {NameMapping.DETAIL_MAP.get(k, k)}: {v} {unit}")

                # 拆解执行动作 (Action)
                actions_found = {k: v for k, v in trigger.items() if k.startswith("Action") and isinstance(v, dict)}

                if actions_found:
                    info.append(f"  [执行动作]")
                    for action_key, aln in actions_found.items():
                        action_label = f" ({action_key})" if len(actions_found) > 1 else ""
                        info.append(f"    - 行为类型{action_label}: {aln.get('type', 'Unknown')}")

                        for k, v in aln.items():
                            if k == "type":
                                continue

                            # --- 修正后的拦截逻辑：同时匹配 planeId 和 planeName ---
                            if k in ["planeId", "planeName"]:
                                label = "飞机型号"
                                value = self.get_localized_plane_name(v)
                            else:
                                label = NameMapping.DETAIL_MAP.get(k, k)
                                value = v

                            # 统一处理单位
                            unit = "s" if k in ["reduceTime", "workTime"] else ""
                            info.append(f"    - {label}: {value}{unit}")

        # 5. 属性加成 (Modifiers)
        mods = rage_data.get("modifiers", {})
        if mods:
            info.append(f"  [加成效果]")
            for k, v in mods.items():
                label = NameMapping.MODIFIER_MAP.get(k, k)

                # 情况 A: 值是一个字典 (如 GSMaxDist)
                if isinstance(v, dict):
                    # 尝试匹配当前舰种
                    factor = v.get(current_species)
                    if factor is not None:
                        percent = round((factor - 1.0) * 100)
                        # 翻译舰种名用于提示
                        type_label = NameMapping.SHIP_CLASS_MAP.get(current_species, current_species)
                        info.append(f"    - {type_label}: {percent:+.0f}%")
                    else:
                        # 如果没有匹配到当前舰种，通常不显示，或者你可以选择遍历显示全部
                        pass

                # 情况 B: 值是 healthRegen (显示为固定数值而非百分比)
                elif k == "healthRegen":
                    info.append(f"    - {label}: 每秒回复 {v:.0f} HP")

                # 情况 C: 普通数值加成 (系数转换)
                elif isinstance(v, (float, int)):
                    if v > 10.0:
                        info.append(f"    - {label}: +{v:.0f}")
                    else:
                        percent = round((v - 1.0) * 100)
                        info.append(f"    - {label}: {percent:+.0f}%")
                else:
                    info.append(f"    - {label}: {v}")

        return info

    # 主/副炮横向散步公式
    def get_dispersion_formula(self, weapon_data):
        """
        根据统一逻辑解析横向散布公式: Rh = (IR-MR)/(ID/1000) * R + MR*30
        """
        ir = weapon_data.get('idealRadius')
        mr = weapon_data.get('minRadius')
        id_dist = weapon_data.get('idealDistance')

        if ir is None or mr is None or id_dist is None:
            return "数据缺失"

        # 1. 计算斜率 (处理 ID 差异)
        slope = (ir - mr) / (id_dist / 1000)
        # 2. 计算截距 (MR * 30)
        intercept = mr * 30

        # 返回格式化后的字符串
        return f"{round(slope, 2)}R + {round(intercept, 2)}"

    # 加载隐蔽插数据
    def load_mod_file(self, mod_filename):
        """
        专门用于从 Modernization 文件夹下提取特定插件的 JSON 数据
        """
        # 增加缓存机制，避免重复读写磁盘
        if hasattr(self, '_cached_mod_data') and mod_filename in self._cached_mod_data:
            return self._cached_mod_data[mod_filename]

        json_path = os.path.join(self.base_dir, "data", "split", "Modernization", f"{mod_filename}.json")

        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if not hasattr(self, '_cached_mod_data'):
                        self._cached_mod_data = {}
                    self._cached_mod_data[mod_filename] = data
                    return data
            except Exception as e:
                self._log(f"提取插件文件 {mod_filename} 失败: {e}")
                return {}  # 返回空字典而不是 None，防止后续 .get() 报错
        else:
            self._log(f"找不到插件文件: {json_path}")
            return {}

    def get_conceal_coeff(self, species, level, nation, ship_index):
        """
        严格按照插件 JSON 的通用过滤条件计算隐蔽系数
        """
        mod_data = self.load_mod_file("PCM027_ConcealmentMeasures_Mod_I")

        # --- 1. 舰长技能逻辑 ---
        if species == "Submarine":
            skill_bonus = 1.0
        elif species == "AirCarrier":
            skill_bonus = 0.85
        else:
            skill_bonus = 0.9

        # --- 2. 插件判定逻辑 ---
        # 提取所有限制条件
        mod_ships = mod_data.get("ships", [])
        mod_excludes = mod_data.get("excludes", [])
        mod_levels = mod_data.get("shiplevel", [])
        mod_types = mod_data.get("shiptype", [])
        mod_nations = mod_data.get("nation", [])

        upgrade_bonus = 1.0  # 默认不计算插件加成

        # 模糊匹配 ship_index (例如 PXSC102)
        is_whitelisted = any(s.startswith(ship_index) for s in mod_ships)
        is_excluded = any(ex.startswith(ship_index) for ex in mod_excludes)

        if is_whitelisted:
            # 白名单：特地标记，直接准许
            upgrade_bonus = 0.9
        elif is_excluded:
            # 黑名单：一票否决
            upgrade_bonus = 1.0
        else:
            # 通用过滤条件：必须全部满足 (Level + Type + Nation)
            if (level in mod_levels and
                    species in mod_types and
                    nation in mod_nations):
                upgrade_bonus = 0.9

        return skill_bonus * upgrade_bonus

    # 新·船体数据解析
    def analyze_ship_data(self, ship_data):
        all_hulls_results = {}
        analyzer = ShipHullDataAnalyze()

        for mod_key, module_data in ship_data.items():
            hull_id = None

            if mod_key in {"HullDefault","Hull_A"}:
                hull_id = "A"
                # 关键：将存储键名改为 A_Hull，让 UI 的 .startswith("A") 能匹配到
                save_key = "A_Hull"
            else:
                match = self.PATTERNS_NEW.get("Hull").match(mod_key)
                if match:
                    hull_id = match.group(1)
                    save_key = mod_key  # 保持 A_Hull, B_Hull 等

            if hull_id:
                try:
                    single_hull_analysis = analyzer.analyzeShipData(module_data, hull_id)
                    # 统一存入 all_hulls_results，确保键名符合 UI 预期的 [Letter]_Hull 格式
                    all_hulls_results[save_key] = single_hull_analysis
                except Exception as e:
                    self._log(f"解析 {mod_key} 失败: {e}")

        return all_hulls_results

    # 新·消耗品数据显示
    def _format_consumable_details(self, info):
        output = []
        """专门处理复杂消耗品信息的显示"""

        isAutoConsumable = "是" if info['isAutoConsumable'] else "否"
        isInterceptor = "是" if info['isInterceptor'] else "否"
        isNoPreparaTime = "（该消耗品无准备时间）" if info['preparationTime'] == 0 else ""

        if info['type'] == "crashCrew":
            output.append(f"扑灭起火、清除进水、并修复受损配件。阻止敌方潜艇发射的鱼雷进行导向。")
        elif info['type'] == "regenCrew":
            data_type = "+" if info['regenHPSpeed'] > 0 else ""
            output.append(f"每秒回复血量: {data_type}{info['regenHPSpeed'] * 100}%")
        elif info['type'] == "airDefenseDisp":
            data_type_1 = "+" if info['areaDmgMultiplier'] > 0 else ""
            data_type_2 = "+" if info['bubbleDmgMultiplier'] > 0 else ""
            output.append(f"防空区域秒伤: {data_type_1}{info['areaDmgMultiplier'] * 100}%")
            output.append(f"黑云伤害: {data_type_2}{info['bubbleDmgMultiplier'] * 100}%")
        elif info['type'] == "fighter":
            raw_name = info.get('fighterName', '未知')
            display_name = self.plane_name_mapping.get(raw_name.upper(), raw_name)
            output.append(f"战斗机名称: {display_name}")
            output.append(f"战斗机数量: {info['fighterNum']}")
            output.append(f"截击机: {isInterceptor}")
            output.append(f"狗斗时间: {info['dogFightTime']}s")
            output.append(f"离开时间: {info['flyAwayTime']}s")
            output.append(f"战斗机爬升角度: {info['flightClimbAngle']}°")
            output.append(f"巡逻半径: {info['radiusToKill'] / 10}km")
            # output.append(f"尝试攻击时间: {info['timeToTryingCatch']}s")
            output.append(f"索敌时间: {info['timeDelayAtk']}s / 瞄准时间: {info['timeWaitDelayAtk']}s")
        elif info['type'] == "scout":
            DistCoeff = info['gunsDistCoeff'] - 1
            data_type = "+" if DistCoeff > 0 else ""
            output.append(f"主炮射程 {data_type}{DistCoeff * 100:.2f}%")
        elif info['type'] == "smokeGenerator":
            output.append(f"烟雾生成半径: {info['radius'] * 3}m")
            output.append(f"烟雾生成高度: {info['height']}m")
            output.append(f"烟雾生成速度限制: {info['speedLimit']}kts")
            output.append(f"烟雾扩散时间: {info['lifeTime']}s")
        elif info['type'] == "speedBoosters":
            data_type_1 = "+" if info['boostCoeff'] > 0 else ""
            data_type_2 = "+" if info['forwardEngForsag'] > 0 else ""
            data_type_3 = "+" if info['backwardEngForsag'] > 0 else ""
            data_type_4 = "+" if info['forwardEngForsagMaxSpd'] > 0 else ""
            data_type_5 = "+" if info['backwardEngForsagMaxSpd'] > 0 else ""
            output.append(f"最高航速: {data_type_1}{info['boostCoeff'] * 100}%")
            output.append(f"推力加成: 前进{data_type_2}{info['forwardEngForsag'] * 100}% / 后退{data_type_3}{info['backwardEngForsag'] * 100}% ")
            output.append(f"加速最大速度倍率: 前进{data_type_4}{info['forwardEngForsagMaxSpd']} / 后退{data_type_5}{info['backwardEngForsagMaxSpd']}")
        elif info['type'] == "sonar":
            ship_dist = info['distShip'] * 0.03
            torp_dist = info['distTorpedo'] * 0.03
            mine_dist = info['distMine'] * 0.03
            output.append(f"舰船探测距离: {ship_dist:.2f} km")
            output.append(f"鱼雷探测距离: {torp_dist:.2f} km")
            output.append(f"水雷探测距离: {mine_dist:.2f} km")
        elif info['type'] == "torpedoReloader":
            output.append(f"鱼雷装填时间: {info['torpedoReloadTime']}s")
        elif info['type'] == "rls":
            ship_dist = info['distShip'] * 0.03
            classes = info.get("affectedClasses", [])
            output.append(f"舰船探测距离: {ship_dist:.2f} km")
            if classes:
                class_str = ", ".join([NameMapping.SHIP_CLASS_MAP.get(c, c) for c in classes])
                output.append(f"限制探测舰种: {class_str}")
        elif info['type'] == "artilleryBoosters":
            BoostCoeff = info['boostCoeff'] - 1
            data_type = "+" if BoostCoeff > 0 else ""
            output.append(f"主炮装填时间: {data_type}{BoostCoeff * 100:.2f}%")
        elif info['type'] == "healForsage":
            data_type = "+" if info['boostCoeff'] > 0 else ""
            output.append(f"引擎冷却速度: {data_type}{info['boostCoeff'] * 100}%")
        elif info['type'] == "callFighters":
            raw_name = info.get('fighterName', '未知')
            display_name = self.plane_name_mapping.get(raw_name.upper(), raw_name)
            output.append(f"战斗机名称: {display_name}")
            output.append(f"战斗机数量: {info['fighterNum']}")
            output.append(f"截击机: {isInterceptor}")
            output.append(f"狗斗时间: {info['dogFightTime']}s")
            output.append(f"离开时间: {info['flyAwayTime']}s")
            output.append(f"战斗机爬升角度: {info['flightClimbAngle']}°")
            output.append(f"巡逻半径: {info['radiusToKill'] / 10}km")
            # output.append(f"尝试攻击时间: {info['timeToTryingCatch']}s")
            output.append(f"索敌时间: {info['timeDelayAtk']}s / 瞄准时间: {info['timeWaitDelayAtk']}s")
        elif info['type'] == "regenerateHealth":
            output.append(f"恢复飞机中队部分生命值。在敌方战斗机攻击时使用能免于被击毁。")
        elif info['type'] == "depthCharges":
            output.append(f"半径: {info['radius'] * 0.003:.2f}km")
        elif info['type'] == "hydrophone":
            output.append(f"虚影存留时间: {info['zoneLifeTime']}s")
            output.append(f"刷新时间: {info['hpUpdFreq']}s")
            output.append(f"视野距离: {info['hpWaveRadius'] * 0.001:.2f}km")
        elif info['type'] == "fastRudders":
            buoyancyRudderTimeCoeff = info['buoyancyRudderTimeCoeff'] - 1
            buoyancySpeedCoeff = info['maxBuoyancySpeedCoeff'] - 1
            data_type_1 = "+" if buoyancyRudderTimeCoeff > 0 else ""
            data_type_2 = "+" if buoyancySpeedCoeff > 0 else ""
            output.append(f"水平舵换挡时间: {data_type_1}{buoyancyRudderTimeCoeff * 100:.2f}%")
            output.append(f"上浮/下潜速度: {data_type_2}{buoyancyRudderTimeCoeff * 100:.2f}%")
        elif info['type'] == "subsEnergyFreeze":
            canUseOnEmpty = "是" if info['canUseOnEmpty'] else "否"
            output.append(f"启用此消耗品后，下潜能力将停止消耗。")
            output.append(f"可在电池耗尽时启用: {canUseOnEmpty}")
        elif info['type'] == "submarineLocator":
            ship_dist = info['distShip'] * 0.03
            output.append(f"舰船探测距离: {ship_dist:.2f} km")
        elif info['type'] == "planeSmokeGenerator":
            output.append(f"烟雾生效延迟: {info['activationDelay']}s")
            output.append(f"烟雾生成半径: {info['radius'] * 3}m")
            output.append(f"烟雾生成高度: {info['height']}m")
            output.append(f"烟雾生成速度限制: {info['speedLimit']}kts")
            output.append(f"烟雾扩散时间: {info['lifeTime']}s")
        elif info['type'] == "vampireDamage":
            output.append(f"用于恢复生命值的伤害转化系数: {info['damageGMHealCoeff'] * 100:.2f}%")
        elif info['type'] == "supportBuoy":
            output.append(f"加成区域: {info['battleDropVisualName']}")
            output.append(f"区域布置时间: {info['battleDropActTime']}s")
            output.append(f"区域持续时间: {info['supportBuoyZoneLifetime']}s")
            output.append(f"区域半径: {info['buffZoneRadius'] / 1000:.2f}km")
            output.append(f"加成效果:")
            output.append(f"效果持续时间: {info['buffDuration']}s")
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
                output.append(f"鱼雷管装填时间: {data_type_5}{gtShotDelay * 100:.2f}%")
                output.append(f"主炮最大散步面积: {data_type_1}{gmIdealRadius * 100:.2f}%")
                output.append(f"主炮装填时间: {data_type_2}{gmShotDelay * 100:.2f}%")
                output.append(f"副炮最大散步面积: {data_type_3}{gsIdealRadius * 100:.2f}%")
                output.append(f"副炮装填时间: {data_type_4}{gsShotDelay * 100:.2f}%")
                output.append(f"副炮射程:")
                for ship_class, boost_val in gs_detail.items():
                    cn_name = NameMapping.SHIP_CLASS_MAP.get(ship_class, ship_class)
                    boost_pct = boost_val - 1
                    if boost_pct != 0:
                        output.append(f"* {cn_name}: +{boost_pct * 100:.2f}%")

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
                output.append(f"方向舵换挡时间: {data_type_2}{sgRudderTime * 100:.2f}%")
                output.append(f"方向舵效率: {data_type_1}{sgRudderPower * 100:.2f}%")
                output.append(f"战舰航速: {data_type_3}{speedCoeff * 100:.2f}%")
                output.append(f"受到的全类型伤害: {data_type_4}{vulnerabilityAll * 100}%")
                output.append(f"每秒回复血量: {data_type_5}{info['healthRegenPercent'] * 100:.2f}%")

        return output

    # TODO:优化原代码
    def analyze(self, display_area, data):
        # 新船体模块数据
        hulls_info = self.analyze_ship_data(data)
        # --- 基础信息处理 ---
        ship_index = data.get("index", "Unknown")
        ship_id = data.get("id", "N/A")

        # --- 2. 舰船名称映射 (只针对 index 处理) ---
        # 强制转字符串并清洗前缀
        raw_key = str(ship_index).upper().replace("IDS_", "").strip()

        # 执行映射查询
        real_name = self.ship_name_mapping.get(raw_key)

        # 如果全名没搜到，尝试截断下划线 (如 PASA598_Wasp -> PASA598)
        if not real_name and "_" in raw_key:
            real_name = self.ship_name_mapping.get(raw_key.split("_")[0])

        # 最终保底：如果字典里实在没有，则显示原始 index
        real_name = real_name or ship_index

        type_info = data.get("typeinfo", {})
        raw_nation = type_info.get("nation", "Unknown")
        raw_species = type_info.get("species", "Unknown")
        raw_group = data.get("group", "standard")
        raw_level = data.get("level", 0)

        # --- 消耗品提取逻辑 ---
        prepared_consumable_data = []  # 存储处理好的中间数据
        ship_abilities = data.get("ShipAbilities", {})
        slot_keys = sorted(ship_abilities.keys(),
                           key=lambda x: int(re.search(r'\d+', x).group()) if re.search(r'\d+', x) else 0)

        for slot_key in slot_keys:
            slot_data = ship_abilities[slot_key]
            abils = slot_data.get("abils", [])

            # 此处进行数据提取和计算，完全不涉及 UI
            slot_items = []
            for abil_pair in abils:
                if isinstance(abil_pair, list) and len(abil_pair) >= 2:
                    file_key = str(abil_pair[0]).strip()
                    config_key = str(abil_pair[1]).strip()
                    stats = self.consumable_analyzer.analyzeConsumableData(file_key, config_key)
                    display_name = self.ability_name_map.get(file_key.upper(), stats.get("titleIDs", file_key))
                    slot_items.append({
                        "name": display_name,
                        "num": stats.get("numConsumables", 0),
                        "config": abil_pair[1],
                        "type": stats.get("consumableType"),
                        "workTime": stats.get("workTime", 0),
                        "preparationTime": stats.get("preparationTime", 0),
                        "reloadTime": stats.get("reloadTime", 0),
                        "isAutoConsumable": stats.get("isAutoConsumable", False),
                        "buoyancyStates": stats.get("availableBuoyancyStates", []),  # 提取列表
                        "regenHPSpeed": stats.get("regenerationHPSpeed", 0),
                        "areaDmgMultiplier": stats.get("areaDamageMultiplier", 0),
                        "bubbleDmgMultiplier": stats.get("bubbleDamageMultiplier", 0),
                        "fighterName": stats.get("fightersName", "Unknown"),
                        "fighterNum": stats.get("fightersNum", 0),
                        "radiusToKill": stats.get("distanceToKill", 0),
                        "dogFightTime": stats.get("dogFightTime", 0),
                        "flyAwayTime": stats.get("flyAwayTime", 0),
                        "flightClimbAngle": stats.get("climbAngle", 0),
                        "isInterceptor": stats.get("isInterceptor", False),
                        "radius": stats.get("radius", 0),
                        "timeDelayAtk": stats.get("timeDelayAttack", 0),
                        "timeToTryingCatch": stats.get("timeToTryingCatch", 0),
                        "timeWaitDelayAtk": stats.get("timeWaitDelayAttack", 0),
                        "gunsDistCoeff": stats.get("artilleryDistCoeff", 0),
                        "speedLimit": stats.get("speedLimit", 0),
                        "height": stats.get("height", 0),
                        "startDelay": stats.get("startDelayTime", 0),
                        "lifeTime": stats.get("lifeTime", 0),
                        "forwardEngForsag": stats.get("forwardEngineForsag", 0),
                        "forwardEngForsagMaxSpd": stats.get("forwardEngineForsagMaxSpeed", 0),
                        "backwardEngForsag": stats.get("backwardEngineForsag", 0),
                        "backwardEngForsagMaxSpd": stats.get("backwardEngineForsagMaxSpeed", 0),
                        "boostCoeff": stats.get("boostCoeff", 0),
                        "distShip": stats.get("distShip", 0),
                        "distTorpedo": stats.get("distTorpedo", 0),
                        "distMine": stats.get("distSeaMine", 0),
                        "torpedoReloadTime": stats.get("torpedoReloadTime", 0),
                        "affectedClasses": stats.get("affectedClasses", []),
                        "hpUpdFreq": stats.get("hydrophoneUpdateFrequency", 0),
                        "hpWaveRadius": stats.get("hydrophoneWaveRadius", 0),
                        "zoneLifeTime": stats.get("zoneLifeTime", 0),
                        "buoyancyRudderResetTimeCoeff": stats.get("buoyancyRudderResetTimeCoeff", 0),
                        "buoyancyRudderTimeCoeff": stats.get("buoyancyRudderTimeCoeff", 0),
                        "maxBuoyancySpeedCoeff": stats.get("maxBuoyancySpeedCoeff", 0),
                        "underwaterMaxRudderAngleCoeff": stats.get("underwaterMaxRudderAngleCoeff", 0),
                        "canUseOnEmpty": stats.get("canUseOnEmpty", False),
                        "activationDelay": stats.get("activationDelay", 0),
                        "updatePeriod": stats.get("updatePeriod", 0),
                        "damageGMHealCoeff": stats.get("modifiers", {}).get("damageGMHealCoeff", 0),
                        "gmIdealRadius": stats.get("GMIdealRadius", 0),
                        "gmShotDelay": stats.get("GMShotDelay", 0),
                        "gsIdealRadius": stats.get("GSIdealRadius", 0),
                        "gsMaxDistDetail": stats.get("GSMaxDist", {}),
                        "gsShotDelay": stats.get("GSShotDelay", 0),
                        "gtShotDelay": stats.get("GTShotDelay", 0),
                        "battleDropActTime": stats.get("battleDropActivationTime", 0),
                        "battleDropName": stats.get("battleDropName", "Unknown"),
                        "battleDropVisualName": stats.get("battleDropVisualName", "Unknown"),
                        "speedCoef": stats.get("speedCoef", 0),
                        "vulnerability": stats.get("vulnerabilityAll", 0),
                        "rudderTime": stats.get("SGRudderTime", 0),
                        "rudderPower": stats.get("SGRudderPower", 0),
                        "buffDuration": stats.get("buffDuration", 0),
                        "buffZoneRadius": stats.get("buffZoneRadius", 0),
                        "supportBuoyZoneLifetime": stats.get("zoneLifetime", 0),
                        "healthRegenPercent": stats.get("healthRegenPercent", 0),
                    })

            if slot_items:
                prepared_consumable_data.append({
                    "slot_num": int(slot_data.get('slot', 0)) + 1,
                    "items": slot_items
                })

        # --- 模块提取核心逻辑 ---
        combined_stats = {}
        drum_configs = {}
        has_pure_b = any(k.startswith("B_") for k in data.keys() if isinstance(data[k], dict))

        for mod_key, module_data in data.items():
            if not isinstance(module_data, dict): continue
            target_letters = []
            current_cat = None

            for category, pattern in self.PATTERNS.items():
                m = pattern.fullmatch(mod_key)
                if m:
                    raw_prefix = m.group(1)
                    prefix = "".join(re.findall(r'[A-Z]+', raw_prefix))
                    target_letters = ["A", "B"] if (prefix == "AB" and has_pure_b) else ["A"] if prefix == "AB" else list(prefix)
                    current_cat = category
                    break

            if not current_cat:
                if "ArtilleryDefault" in mod_key:
                    current_cat = "Artillery"
                elif "ATBADefault" in mod_key:
                    current_cat = "ATBA"
                elif "AirDefenseDefault" in mod_key:
                    current_cat = "AirDefense"
                # Default 模块默认映射给全舰（以 A 为代表）
                if current_cat: target_letters = ["A"]

            if not target_letters: continue

            # 初始化数据桶
            for letter in target_letters:
                if letter not in combined_stats:
                    combined_stats[letter] = {cat: [] for cat in self.PATTERNS.keys()}

            # 1. 舰载机中队 (提取逻辑核心修复：放在最前面并直接 continue)
            if current_cat in ["DiveBomber", "TorpedoBomber", "Fighter", "SkipBomber"]:
                planes = module_data.get("planes", [])
                if planes:
                    info = {"type": current_cat, "planes": planes}
                    for letter in target_letters:
                        # 避免重复配置
                        if info not in combined_stats[letter][current_cat]:
                            combined_stats[letter][current_cat].append(info)
                continue # 处理完飞机，跳过该模块后续的所有 HP 子键匹配

            # 3. 空袭处理 (增强版：递归识别所有类型的空袭)
            elif current_cat == "AirSupport":
                found_list = []
                # 递归扫描：不管是根目录还是 A1_ 这种子目录下，只要包含 Armament 且是字典就抓取
                def scan_as(d):
                    for k, v in d.items():
                        if isinstance(v, dict) and "Armament" in k:
                            found_list.append({
                                "ui_type": v.get("uiType", "damage"),
                                "plane_id": v.get("planeName", "Unknown"),
                                "charges": v.get("chargesNum", 0),
                                "reload": v.get("reloadTime", 0),
                                "work_time": v.get("workTime"),  # Helper 类型特有
                                "max_dist": v.get("maxDist", 0),
                                "min_dist": v.get("minDist", 0),
                                "is_fixed": v.get("useFixedTimeToAttackPoint", False)
                            })
                scan_as(module_data)

                for letter in target_letters:
                    if "AirSupport" not in combined_stats[letter]:
                        combined_stats[letter]["AirSupport"] = []
                    # 避免重复添加
                    for item in found_list:
                        if item not in combined_stats[letter]["AirSupport"]:
                            combined_stats[letter]["AirSupport"].append(item)
                continue # 关键：空袭不需要进入下方的 HP_PATTERNS 逻辑

            # 弹夹炮逻辑
            if current_cat == "Artillery":
                switch_conf = module_data.get("SwitchableModeArtilleryModule")
                drum_conf = module_data.get("DrumArtilleryModule")
                mode_info = None
                conf = switch_conf or drum_conf
                if conf:
                    mode_data = {
                        "type": "未知模式",
                        "reload": 0,
                        "count": 0,
                        "delay": 0,
                        "buffs": [],
                        "charge": ""
                    }

                    # A. 判定模式类型并抓取基础参数
                    if switch_conf:
                        mode_info = {
                            "header": "连发射击模式",
                            "details": [
                                f"长装填: {switch_conf.get('fullReloadTime', 0)}s",
                                f"连发数量: {switch_conf.get('shotsCount', 0):.0f}",
                                f"连发间隔: {switch_conf.get('burstReloadTime', 0)}s"
                            ],
                            "modifiers": switch_conf.get("modifiers", {})
                        }

                    elif drum_conf:
                        is_switchable = drum_conf.get("isSwitchable", False)
                        is_chargeable = drum_conf.get("isChargeable", False)
                        n_rounds = drum_conf.get('shotsCount', 2)
                        full_reload = drum_conf.get('fullReloadTime', 0)
                        shot_delay = drum_conf.get('shotDelay', 0)
                        params = drum_conf.get("chargeTimeParams", [])

                        switch_prefix = "可切换" if is_switchable else "强制"

                        # --- 1. 模式判定与标题设置 ---
                        if is_chargeable:
                            header_name = f"弹鼓炮"
                            details = [
                                f"连发数量: {n_rounds:.0f}",
                                f"连发间隔: {shot_delay}s"
                            ]

                            # --- 2. 弹鼓模式下的阶梯逻辑 (mode_type 1 & 2) ---
                            if len(params) >= 3:
                                mode_type = params[2]
                                if mode_type == 1:
                                    details.append(f"第 1 轮装填时间: {params[0]}s")
                                    details.append(f"第 2 ~ {n_rounds:.0f} 轮装填时间: {params[1]}s")
                                elif mode_type == 2:
                                    details.append(f"第 1 ~ {n_rounds - 1:.0f} 轮装填时间: {params[0]}s")
                                    details.append(f"第 {n_rounds:.0f} 轮(末轮)装填时间: {params[1]}s")

                        else:
                            # --- 3. 弹夹模式逻辑 (isChargeable 为 False) ---
                            header_name = f"{switch_prefix}连发射击-弹夹炮"
                            details = [
                                f"长装填时间: {full_reload}s",
                                f"连发间隔: {shot_delay}s",
                                f"连发轮数: {n_rounds:.0f}"
                            ]

                        mode_info = {
                            "header": header_name,
                            "details": details,
                            "modifiers": drum_conf.get("modifiers", {})
                        }

                    # D. 存储到对应的炮塔字母
                    buffs = []
                    mods = mode_info.get("modifiers", {})
                    if mods:
                        buffs.append("- 加成效果:")
                        for mk, mv in mods.items():
                            label = NameMapping.MODIFIER_MAP.get(mk, mk)
                            if isinstance(mv, (float, int)):
                                p = round((mv - 1.0) * 100)
                                buffs.append(f" - {label}: {p:+.0f}%")
                    mode_info["buff_list"] = buffs

                    # 映射至炮塔
                    found_groups = re.findall(r'([A-Z]+)\d*_', mod_key)
                    for group in found_groups:
                        # 如果匹配到的是 "AB"，则拆分为 "A" 和 "B" 分别存储
                        for letter in list(group):
                            drum_configs[letter] = mode_info

            # 4. 通用武器提取 (主/副/鱼雷/防空)
            if current_cat in ["Artillery", "ATBA", "AirDefense", "Torpedoes", "DepthChargeGuns"]:
                check_cats = [current_cat]
                if current_cat in ["Artillery", "ATBA"]:
                    check_cats.append("AirDefense")

                system_wide_info = {
                    "max_dist": module_data.get("maxDist", 0),
                    "sigma": module_data.get("sigmaCount", "N/A"),
                }

                for letter in target_letters:
                    # 如果是主炮或副炮分类，记录其系统精度
                    if current_cat in ["Artillery", "ATBA"]:
                        combined_stats[letter][f"{current_cat}_System"] = system_wide_info

                for sk, sv in module_data.items():
                    if not isinstance(sv, dict): continue

                    # A. 识别防空圈 (Aura, Far, Medium, Near)
                    if any(kw in sk for kw in ["Aura", "Far", "Medium", "Near"]):
                        raw_id = sv.get("name", sk)
                        display_name = self.get_localized_weapon_name(raw_id)
                        is_bubble_layer = "_Bubbles" in sk

                        # 取防空圈本身的基础伤害
                        net_dmg = sv.get("areaDamage", 0)
                        net_period = sv.get("areaDamagePeriod", 0)

                        info = {
                            "id": sk,
                            "name": display_name,
                            "is_aura": True,
                            "is_bubble_layer": is_bubble_layer,
                            "min_dist": sv.get("minDistance", 0),
                            "max_dist": sv.get("maxDistance", 0),
                            "net_dmg": net_dmg,
                            "final_dmg": round(net_dmg/net_period, 2),
                            "hit_chance": sv.get("hitChance", 0),
                            "bubble_dmg": (sv.get("bubbleDamage", 0)*7),
                            "bubbles": int(sv.get("outerBubbleCount", 0) + sv.get("innerBubbleCount", 0))
                        }
                        for letter in target_letters:
                            combined_stats[letter]["AirDefense"].append(info)
                        continue

                    # B. 识别普通炮座 (HP_XGA, HP_AGS 等)
                    matched_cat = None
                    for cat in check_cats:
                        if self.HP_PATTERNS.get(cat) and self.HP_PATTERNS[cat].fullmatch(sk):
                            matched_cat = cat
                            break

                    if matched_cat:
                        raw_id = sv.get("name", sk)
                        # --- 使用兼容方法获取名称 ---
                        display_name = self.get_localized_weapon_name(raw_id)
                        guns_list = sv.get("Guns", [])
                        barrels = guns_list[0].get("numBarrels", sv.get("numBarrels", 0)) if guns_list else sv.get(
                            "numBarrels", 0)
                        weapon_info = {
                            "id": sk,
                            "name": display_name,
                            "is_aura": False,
                            "barrels": barrels,
                            "reload_time": guns_list[0].get("shotDelay",sv.get("shotDelay", 0)) if guns_list else sv.get("shotDelay", 0),
                            "ammo": sv.get("ammoList", guns_list[0].get("ammoList", []) if guns_list else []),

                            # --- 从当前炮塔 sv 中提取散布核心参数 ---
                            "idealRadius": sv.get("idealRadius"),
                            "minRadius": sv.get("minRadius"),
                            "idealDistance": sv.get("idealDistance"),

                            "r_zero": sv.get("radiusOnZero", 0),
                            "r_delim": sv.get("radiusOnDelim", 0),
                            "r_max": sv.get("radiusOnMax", 0),
                            "delim": sv.get("delim", 0)
                        }
                        for letter in target_letters:
                            combined_stats[letter][matched_cat].append(weapon_info)

        # --- 最终渲染显示 ---

        # --- UI 渲染基础信息 ---
        display_area.insert(tk.END, f"舰船名称: {real_name}\n")
        display_area.insert(tk.END, f"舰船ID: {ship_id}\n")
        display_area.insert(tk.END, f"舰船编号: {ship_index}\n")
        display_area.insert(tk.END, f"所属国家: {NameMapping.NATION_MAP.get(raw_nation, raw_nation)}\n")
        display_area.insert(tk.END, f"舰船种类: {NameMapping.SHIP_CLASS_MAP.get(raw_species, raw_species)}\n")
        level_roman = NameMapping.LEVEL_MAP[raw_level] if 0 <= raw_level < len(NameMapping.LEVEL_MAP) else str(raw_level)
        display_area.insert(tk.END, f"舰船等级: {level_roman}\n")
        display_area.insert(tk.END, f"舰船类别: {NameMapping.SHIP_GROUP_MAP.get(raw_group, raw_group)}\n\n")

        # --- 消耗品渲染部分 ---
        if prepared_consumable_data:
            display_area.insert(tk.END, "=== 舰船消耗品配置 ===\n")
            for slot in prepared_consumable_data:
                display_area.insert(tk.END, f"[槽位 {slot['slot_num']}]\n")
                for item in slot['items']:
                    num_val = "无限" if item['num'] == -1 else item['num']
                    display_area.insert(tk.END, f"  - 可选消耗品类型:{item['name']}[{item['config']}]\n"
                                                f"    - 可用数量:{num_val} \n")
                    details = self._format_consumable_details(item)
                    if details:
                        display_area.insert(tk.END, "    - 消耗品效果:\n")
                        for line in details:
                            display_area.insert(tk.END, f"        - {line}\n")

            display_area.insert(tk.END, "\n")  # 最后补一个空行

        # 防空炮
        for letter in combined_stats:
            ad_list = combined_stats[letter].get("AirDefense", [])
            # 1. 过滤出持续伤害层（排除黑云），按射程从远到近排序
            dps_layers = sorted([x for x in ad_list if x.get('is_aura') and not x['is_bubble_layer']],
                               key=lambda x: x['max_dist'], reverse=True)

            # 2. 从最外圈开始向内累加伤害
            cumulative_dmg = 0
            for layer in dps_layers:
                cumulative_dmg += layer['net_dmg']
                layer['dmg'] = round(cumulative_dmg, 2) # 更新为面板显示的叠加值

        all_letters = sorted(combined_stats.keys())
        for letter in all_letters:
            display_area.insert(tk.END, f"=== {letter} 船体详情 ===\n")
            config = combined_stats[letter]

            # 1. 船体基础信息
            mod_key = next((k for k in hulls_info.keys() if k.startswith(letter)), None)
            if not mod_key or mod_key not in hulls_info:
                display_area.insert(tk.END, "  (未找到对应的模块数据)\n")
                continue

            base = hulls_info[mod_key]["default_data"]["items"]
            sub = hulls_info[mod_key]["submarine_sp_data"]["items"]
            conceal_coeff = self.get_conceal_coeff(raw_species, raw_level, raw_nation, ship_index)
            buoyancy_list = sub['buoyancyStates'].get('val')
            invul_data = next((item for item in buoyancy_list if item['state'] == 'DEEP_WATER_INVUL'), {})
            invul_speed_multiplier = invul_data.get('speed_multiplier', 1.0) # 默认 1.0 防止报错
            display_area.insert(tk.END, f"  基础血量: {base['health']['val']}\n"
                                        f"  基础最大航速: {base['maxSpeed']['val']} {base['maxSpeed']['unit']}\n"
                                        f"    - 引擎出力: {base['engine_power']['val']:.0f} {base['engine_power']['unit']}\n"
                                        f"  转向半径: {base['turningRadius']['val']} {base['turningRadius']['unit']}\n"
                                        f"  基础转舵时间: {base['rudderTime']['val']:.2f} {base['rudderTime']['unit']}\n"
                                        f"  隐蔽:\n"
                                        f"    - 对海隐蔽: {base['vis_sea']['val']} {base['vis_sea']['unit']} (最小: {round(base['vis_sea']['val'] * conceal_coeff, 2)} {base['vis_sea']['unit']})\n"
                                        f"    - 对空隐蔽: {base['vis_plane']['val']} {base['vis_plane']['unit']} (最小: {round(base['vis_plane']['val'] * conceal_coeff, 2)} {base['vis_plane']['unit']})\n"
                                        f"  血量回复率: {base['hull_regenper']['val'] * 100:.0f}%")
            if base['has_cit']['val']:
                display_area.insert(tk.END, f"/{base['cit_regenper']['val'] * 100:.0f}%\n")
            else:
                display_area.insert(tk.END, f"/0%（该舰船无核心区模块）\n")
            if raw_species == "Submarine":
                display_area.insert(tk.END, f"  潜艇专有数据:\n"
                                            f"    - 基础水平舵换挡时间: {sub['buoyancy_rudder_time']['val']:.2f} {sub['buoyancy_rudder_time']['unit']}\n"
                                            f"    - 最大上浮和下潜速度: {sub['buoyancy_speed']['val']} {sub['buoyancy_speed']['unit']}\n"
                                            f"    - 最大水下航速 {base['maxSpeed']['val'] * invul_speed_multiplier:.2f} {base['maxSpeed']['unit']}\n"
                                            f"    - 深度数据:\n")
                b_map = {item['state']: item for item in buoyancy_list}
                order = ["SURFACE", "PERISCOPE", "DEEP_WATER", "DEEP_WATER_INVUL"]
                for state_key in order:
                    if state_key in b_map:
                        data = b_map[state_key]
                        cn_name = NameMapping.DEPTH_MAP.get(state_key, state_key)  # 使用你的 DEPTH_MAP 转换
                        d_range = data.get('depth_range', [0, 0])

                        # 独立显示每一行，数字部分做了右对齐微调，让排版更整齐
                        display_area.insert(tk.END,
                                            f"        ◈ [{cn_name}]: {d_range[0]:>5}m 至 {d_range[1]:>5}m\n"
                                            )
                if sub['has_battery']['val']:
                    display_area.insert(tk.END, f"    - 下潜能力:\n"
                                                f"      - 基础电池容量: {sub['bat_cap']['val']}\n"
                                                f"      - 基础电力恢复速度: {sub['bat_regen']['val']} {sub['bat_regen']['unit']}\n")
                if sub['has_hydrophone']['val']:
                    work_states = [NameMapping.DEPTH_MAP.get(s, s) for s in sub['hp_work_states']['val']]
                    detect_states = [NameMapping.DEPTH_MAP.get(s, s) for s in sub['hp_detect_states']['val']]
                    display_area.insert(tk.END, f"    - 水听器:\n"
                                                f"      - 生效半径: {sub['hp_radius']['val']/1000} {sub['hp_radius']['unit']}\n"
                                                f"      - 刷新周期: {sub['hp_frep']['val']} {sub['hp_frep']['unit']}\n"
                                                f"      - 水听器工作层级: {' / '.join(work_states)}\n"
                                                f"      - 可探测深度层级: {' / '.join(detect_states)}\n")
            display_area.insert(tk.END, "-" * 40 + "\n\n")

            # 2. 飞机属性提前显示
            plane_sections = [
                ("Fighter", "攻击机中队"),
                ("DiveBomber", "轰炸机中队"),
                ("TorpedoBomber", "鱼雷轰炸机中队"),
                ("SkipBomber", "跳弹轰炸机中队")
            ]
            for cat_key, cat_label in plane_sections:
                items = config.get(cat_key, [])
                if items:
                    display_area.insert(tk.END, f"  {cat_label}:\n")
                    for idx, item in enumerate(items, 1):
                        # 获取原始 ID 列表
                        raw_planes = item.get("planes", [])
                        # 对每个飞机 ID 进行映射翻译
                        translated_planes = [self.get_localized_plane_name(p) for p in raw_planes]

                        # 使用翻译后的名称生成字符串
                        planes_str = " / ".join(translated_planes)
                        display_area.insert(tk.END, f"    - 飞机型号-{idx}: {planes_str}\n")
                    display_area.insert(tk.END, "-" * 40 + "\n\n")

            # 3. 战斗指令 (RageMode)
            if "A_Specials" in data and "RageMode" in data["A_Specials"]:
                # 传入 raw_species 以便只显示当前舰种的加成
                rage_details = self.parse_rage_mode_advanced(data["A_Specials"]["RageMode"], ship_index, raw_species)
                for line in rage_details:
                    display_area.insert(tk.END, line + "\n")
                display_area.insert(tk.END, "-" * 40 + "\n\n")

            # 空袭
            as_items = config.get("AirSupport", [])
            if as_items:
                display_area.insert(tk.END, "  空袭列表:\n")
                ui_map = {
                    "spy": "情报侦察机",
                    "smoke": "烟幕释放机",
                    "scout": "伴航校射侦察机",
                    "damage": "空袭",
                    "asw": "反潜空袭"  # 建议区分 damage 和 asw，便于识别
                }
                for as_conf in as_items:
                    u_type = as_conf['ui_type']
                    label = ui_map.get(u_type, u_type.capitalize())

                    # --- 新增：本地化映射逻辑 ---
                    raw_plane_id = as_conf.get('plane_id', 'Unknown')
                    translated_plane_name = self.get_localized_plane_name(raw_plane_id)
                    # ---------------------------

                    # 处理 Infinity 情况
                    max_d = as_conf['max_dist']
                    dist_str = f"{as_conf['min_dist']}-{max_d}m" if str(
                        max_d).lower() != 'inf' and max_d < 999999 else "全图范围"

                    # 使用翻译后的名称 translated_plane_name
                    display_area.insert(tk.END, f"    - [{label}] 型号: {translated_plane_name}\n")
                    display_area.insert(tk.END,
                                        f"      数量: {as_conf['charges']} | 装填: {as_conf['reload']}s | 可选择范围: {dist_str}\n")
                    if as_conf.get('work_time'):
                        display_area.insert(tk.END, f"      持续/作用时间: {as_conf['work_time']}s\n")
                display_area.insert(tk.END, "-" * 40 + "\n\n")

            # 4. 其他武器系统 (主炮/副炮/鱼雷/防空/深弹)
            weapon_sections = [
                ("Artillery", "主炮"), ("ATBA", "副炮"),
                ("Torpedoes", "鱼雷"), ("AirDefense", "防空炮"),
                ("DepthChargeGuns", "深弹")
            ]
            for cat_key, cat_label in weapon_sections:
                items = config.get(cat_key, [])
                # 弹夹炮逻辑检测
                is_drum = (cat_key == "Artillery" and letter in drum_configs)
                if not items and not is_drum:
                    continue

                # --- 修改点: 在此处统一定义并排序要显示的 items，确保后续 AirDefense 判断不报错 ---
                valid_items = [x for x in items if isinstance(x, dict) and 'id' in x]
                sorted_items = sorted(valid_items, key=lambda x: x.get('id', ''))

                if is_drum:
                    d = drum_configs[letter]
                    display_area.insert(tk.END, f"  {d['header']}属性:\n")  # 使用 info 中的 header (如：连发射击模式)
                    # 1. 渲染 details 列表中的阶梯装填或基础详情
                    for detail in d.get('details', []):
                        display_area.insert(tk.END, f"    - {detail}\n")

                    # 2. 渲染加成效果 (处理缩进样式)
                    for b in d.get('buff_list', []):
                        if b.startswith(" -"):  # 具体的加成项
                            display_area.insert(tk.END, f"       {b}\n")
                        else:  # “加成效果:” 标题
                            display_area.insert(tk.END, f"    {b}\n")
                    display_area.insert(tk.END, "-" * 40 + "\n\n")

                if cat_key == "AirDefense":
                    display_area.insert(tk.END, f"  {cat_label} 总计:\n")

                    # 1. 渲染持续伤害 (面板秒伤)
                    dps_layers = [a for a in sorted_items if a.get('is_aura') and not a.get('is_bubble_layer')]
                    if dps_layers:
                        display_area.insert(tk.END, "    [面板秒伤]:\n")
                        for a in dps_layers:
                            # 确定射程标签
                            display_area.insert(tk.END,
                                                f"      - {a['name']}:\n        射程: {a['min_dist']}-{a['max_dist']}m | 防空圈基础伤害: {a['net_dmg']} | 防空圈秒伤: {a['final_dmg']} | 命中率: {int(a['hit_chance'] * 100)}%\n")

                    # 2. 渲染黑云
                    bubble_layers = [a for a in sorted_items if a.get('is_bubble_layer')]
                    if bubble_layers:
                        display_area.insert(tk.END, "    [爆炸属性]:\n")
                        for b in bubble_layers:
                            display_area.insert(tk.END,
                                                f"      - {b['name']}:\n        射程: {b['min_dist']}-{b['max_dist']}m | 爆炸伤害: {b['bubble_dmg']} | 数量: {b['bubbles']} 朵\n")

                    # 3. 实体炮座统计 (合并同型号显示)
                    guns = [x for x in sorted_items if not x.get('is_aura')]
                    if guns:
                        display_area.insert(tk.END, "    [防空炮座统计]:\n")
                        counts = {}
                        for g in guns:
                            name = g.get('name', 'Unknown')
                            counts[name] = counts.get(name, 0) + 1
                        for name, count in sorted(counts.items()):
                            display_area.insert(tk.END, f"      - {name} x{count}\n")

                else:
                    # 主炮/副炮等其他武器
                    display_area.insert(tk.END, f"  {cat_label} 总计:\n")
                    system_key = f"{cat_key}_System"
                    if system_key in config:
                        sys_data = config[system_key]
                        max_dist = sys_data.get("max_dist", 0)
                        sigma = sys_data.get("sigma", "N/A")

                        if max_dist > 0:
                            # 转换为公里 (km) 显示
                            dist_km = max_dist / 1000
                            display_area.insert(tk.END,
                                                f"    - 基础最大射程: {dist_km:.2f} km\n"
                                                f"    - Sigma: {sigma}\n")
                    # 同样按数据名字进行分组统计显示，避免主炮/副炮位也出现 1-32 号刷屏
                    wp_counts = {}
                    for item in valid_items:
                        raw_id = item.get('name', 'Unknown')
                        name = self.get_localized_weapon_name(raw_id)
                        barrels = item.get('barrels')
                        reload_val = item.get('reload_time')
                        ammo = tuple(item.get('ammo', []))
                        iR = item.get('idealRadius',0)
                        mR = item.get('minRadius',0)
                        iD = item.get('idealDistance',0)
                        rz = item.get('r_zero', 0)
                        rd = item.get('r_delim', 0)
                        rm = item.get('r_max', 0)
                        dl = item.get('delim', 0)
                        key = (name, barrels, reload_val, ammo, iR, mR, iD, rz, rd, rm, dl)
                        wp_counts[key] = wp_counts.get(key, 0) + 1

                    # 1. 初始化缓冲区，减少 UI 刷新次数
                    buffer = []

                    for (name, barrels, reload_val, ammo, iR, mR, iD, rz, rd, rm, dl), count in wp_counts.items():

                        # 2. 构建美观的弹药列表
                        if ammo:
                            display_ammo_list = []
                            for aid in ammo:
                                clean_id = aid.replace("IDS_", "").upper().strip()
                                a_name = self.ammo_name_mapping.get(clean_id) or aid
                                # 如果找到翻译且与原 ID 不同，则显示 "名称 (ID)"
                                if a_name != aid:
                                    display_ammo_list.append(f"{a_name} ({aid})")
                                else:
                                    display_ammo_list.append(aid)
                        else:
                            display_ammo_list = None

                        # 3. 统一构建格式化文本片段
                        # 提取公共部分
                        if cat_key == "Torpedoes":
                            buffer.append(f"    - 鱼雷发射管: {name} (x{count})\n")
                            buffer.append(f"      - 联装数: {barrels:.0f}\n")
                            buffer.append(f"      - 装填时间: {reload_val} s\n")
                        elif cat_key == "DepthChargeGuns":
                            buffer.append(f"    - 深水炸弹: {name} (x{count})\n")
                            buffer.append(f"      - 联装数: {barrels:.0f}\n")
                            buffer.append(f"      - 装填时间: {reload_val} s\n")
                        else:
                            # 主副炮逻辑
                            temp_data = {"idealRadius": iR, "minRadius": mR, "idealDistance": iD}
                            h_formula = self.get_dispersion_formula(temp_data)

                            buffer.append(f"    - 炮塔: {name} (x{count})\n")
                            buffer.append(f"      - 联装数: {barrels:.0f}\n")
                            buffer.append(f"      - 装填时间: {reload_val} s\n")
                            buffer.append(f"      - 横向散布公式: {h_formula}\n")
                            buffer.append(f"      - 纵向散步系数: {rz} ~ {rd} (R={dl * 100:.0f}%) ~ {rm}\n")

                        # 4. 统一处理弹药展示
                        buffer.append(f"      - 可用弹药:\n")
                        if display_ammo_list:
                            for ammo_item in display_ammo_list:
                                buffer.append(f"        - {ammo_item}\n")
                        else:
                            buffer.append(f"        - 无\n")

                        buffer.append("-" * 40 + "\n\n")

                    # 5. 一次性插入 UI
                    display_area.insert(tk.END, "".join(buffer))