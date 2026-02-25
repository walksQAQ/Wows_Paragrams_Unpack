import os
import json
import re
import sys
import tkinter as tk

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

    BUFF_MAP = {
        "GMIdealRadius": "主炮最大散步",
        "GMPenetrationCoeffHE": "主炮高爆弹穿深",
        "GMMaxDist": "主炮最大射程",
        "GMDamageCoeff": "主炮炮弹标伤",
        "GMAPDamageCoeff": "主炮穿甲弹标伤",
        "artilleryKruppMultiplier": "主炮穿甲弹穿深",
        "torpedoDamageCoeff": "鱼雷标伤",
        "torpedoRangeCoefficient": "鱼雷射程",
        "allConsumableReloadTime": "消耗品的准备和装填时间",
        "planeSpawnTime": "中队整备时间",
        "GSShotDelay": "副炮装填时间",
        "GSIdealRadius": "副炮最大散步",
        "GSMaxDist": "副炮最大射程",
        "GSPenetrationCoeffHE": "副炮高爆弹穿深",
        "healthRegen": "每秒回复血量",
        "AAAuraDamage": "防空炮每秒伤害",
        "vulnerabilityBurn": "受到的火灾伤害",
        "vulnerabilityFlood": "受到的进水伤害"
    }

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

    SPECIES_MAP = {
        "Destroyer": "驱逐舰",
        "Cruiser": "巡洋舰",
        "Battleship": "战列舰",
        "AirCarrier": "航空母舰",
        "Submarine": "潜艇",
        "Auxiliary": "其他"
    }

    def __init__(self):
        # 使用脚本所在绝对路径，增加健壮性
        if getattr(sys, 'frozen', False):
            # 如果是打包后的 EXE 运行，sys.executable 是 EXE 的全路径
            # 我们取它的目录名
            self.base_dir = os.path.dirname(sys.executable)
        else:
            # 如果是源码运行
            self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.ability_name_map = {}
        self.ship_name_mapping = {}
        self.rage_name_mapping = {}
        self.gun_name_mapping = {}
        self.ammo_name_mapping = {}
        self.initialize_mapping()

    def initialize_mapping(self):
        self.load_ability_map()
        self.load_name_mapping()
        self.load_rage_name_mapping()
        self.load_gun_name_mapping()
        self.load_ammo_name_mapping()

    def reload_mappings(self):
        """
        供外部（MainUI）调用的重新初始化接口
        当 POToolkit 更新了 json 文件后，点击按钮即可刷新内存中的字典
        """
        print("正在重新加载本地化数据...")
        # 重新执行一遍所有的加载方法
        self.initialize_mapping()
        print("数据刷新完成。")

    def load_name_mapping(self):
        mapping_path = os.path.join(self.base_dir, "data", "ship_names.json")
        try:
            if os.path.exists(mapping_path):
                with open(mapping_path, 'r', encoding='utf-8') as f:
                    self.ship_name_mapping = json.load(f)
        except Exception as e:
            print(f"读取船名映射出错: {e}")

    def load_ability_map(self):
        file_path = os.path.join(self.base_dir, "data", "ability_names.json")
        try:
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    raw_json = json.load(f)
                    self.ability_name_map = {k.upper(): v for k, v in raw_json.items()}
        except Exception as e:
            print(f"读取技能映射出错: {e}")

    def load_rage_name_mapping(self):
        """加载从 .po 文件提取的战斗指令名称映射表"""
        mapping_path = os.path.join(self.base_dir, "data", "rage_mode_names.json")
        try:
            if os.path.exists(mapping_path):
                with open(mapping_path, 'r', encoding='utf-8') as f:
                    self.rage_name_mapping = json.load(f)
        except Exception as e:
            print(f"读取战斗指令名称映射出错: {e}")

    def load_gun_name_mapping(self):
        """加载由 POToolKit 生成的武器翻译字典"""
        # 注意：这里的路径要与 MainUI 生成的路径一致
        guns_json_path = os.path.join(self.base_dir, "data", "guns_names.json")
        if os.path.exists(guns_json_path):
            try:
                with open(guns_json_path, 'r', encoding='utf-8') as f:
                    self.gun_name_mapping = json.load(f)
            except Exception as e:
                print(f"加载武器翻译失败: {e}")

    def load_ammo_name_mapping(self):
        """加载由 POToolKit 生成的弹药翻译字典"""
        # 路径指向 POToolkit 生成的 ammo_names.json
        ammo_json_path = os.path.join(self.base_dir, "data", "ammo_names.json")
        if os.path.exists(ammo_json_path):
            try:
                with open(ammo_json_path, 'r', encoding='utf-8') as f:
                    self.ammo_name_mapping = json.load(f)
            except Exception as e:
                print(f"加载弹药翻译失败: {e}")

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

    def get_localized_ammo_names(self, ammo_list):
        """
        专门执行弹药表查询的代码块
        输入: ['PAPA001_...', 'PAPA002_...']
        返回: '203 mm AP Mk19 / 203 mm HE/HC Mk25'
        """
        if not ammo_list:
            return "无"

        translated = []
        for ammo_id in ammo_list:
            # 清洗 ID：去掉 IDS_ 前缀并转大写
            clean_id = ammo_id.replace("IDS_", "").upper().strip()

            # 1. 优先从弹药映射表找
            # 2. 找不到则去武器映射表找
            # 3. 再找不到显示原始 ID
            name = self.ammo_name_mapping.get(clean_id) or \
                   self.gun_name_mapping.get(clean_id) or \
                   ammo_id
            translated.append(name)

        return " / ".join(translated)

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
                        elif k == "subRibbons" and isinstance(v, list):
                            # 将 rid 转为字符串去匹配 map，如果找不到则显示 "未知勋带(ID)"
                            ribbon_names = []
                            for rid in v:
                                name = self.RIBBON_MAP.get(str(rid), f"未知勋带({rid})")
                                ribbon_names.append(name)

                            # 格式化输出： 勋带名称1, 勋带名称2 (原始ID列表)
                            info.append(f"    - {self.DETAIL_MAP.get(k, k)}: {', '.join(ribbon_names)}")
                        else:
                            unit = "m" if k == "radius" else ""
                            info.append(f"    - {self.DETAIL_MAP.get(k, k)}: {v} {unit}")

                # 拆解执行动作 (Action)
                actions_found = {k: v for k, v in trigger.items() if k.startswith("Action") and isinstance(v, dict)}

                if actions_found:
                    info.append(f"  [执行动作]")
                    for action_key, aln in actions_found.items():
                        # 如果有多个 Action，打印一下标识（可选）
                        action_label = f" ({action_key})" if len(actions_found) > 1 else ""
                        info.append(f"    - 行为类型{action_label}: {aln.get('type', 'Unknown')}")

                        for k, v in aln.items():
                            if k != "type":
                                label = self.DETAIL_MAP.get(k, k)
                                unit = "s" if k == "reduceTime" else ""
                                info.append(f"    - {label}: {v}{unit}")

        # 5. 属性加成 (Modifiers)
        mods = rage_data.get("modifiers", {})
        if mods:
            info.append(f"  [加成效果]")
            for k, v in mods.items():
                label = self.BUFF_MAP.get(k, k)

                # 情况 A: 值是一个字典 (如 GSMaxDist)
                if isinstance(v, dict):
                    # 尝试匹配当前舰种
                    factor = v.get(current_species)
                    if factor is not None:
                        percent = round((factor - 1.0) * 100)
                        # 翻译舰种名用于提示
                        type_label = self.SPECIES_MAP.get(current_species, current_species)
                        info.append(f"    - {label}: {percent:+.0f}%")
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

    def analyze(self, display_area, data):
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

        nation_map = {
            "USA": "美国", "Japan": "日本", "Germany": "德国", "Russia": "苏联",
            "United_Kingdom": "英国", "France": "法国", "Italy": "意大利", "Pan_Asia": "泛亚",
            "Europe": "欧洲", "Netherlands": "荷兰", "Commonwealth": "英联邦",
            "Pan_America": "泛美", "Spain": "西班牙", "Events": "其他"
        }
        group_map = {
            "start": "初始", "preserved": "已移除", "upgradeable": "可研发", "earlyAccess": "抢先体验",
            "superShip": "超级战舰", "premium": "加值", "ultimate": "特殊", "special": "特殊",
            "specialUnsellable": "特殊", "disabled": "禁用", "clan": "军团", "coopOnly": "仅人机",
            "demoWithoutStatsPrem": "加值测试", "demoWithoutStats": "测试", "unavailable": "不可用"
        }
        roman_map = ["0", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "★"]

        # --- UI 渲染基础信息 ---
        display_area.insert(tk.END, f"舰船名称: {real_name}\n")
        display_area.insert(tk.END, f"ID: {ship_id}\n")
        display_area.insert(tk.END, f"编号: {ship_index}\n")
        display_area.insert(tk.END, f"所属国家: {nation_map.get(raw_nation, raw_nation)}\n")
        display_area.insert(tk.END, f"舰船种类: {self.SPECIES_MAP.get(raw_species, raw_species)}\n")
        level_roman = roman_map[raw_level] if 0 <= raw_level < len(roman_map) else str(raw_level)
        display_area.insert(tk.END, f"舰船等级: {level_roman}\n")
        display_area.insert(tk.END, f"舰船类别: {group_map.get(raw_group, raw_group)}\n\n")

        # --- 消耗品逻辑 ---
        ship_abilities = data.get("ShipAbilities", {})
        ability_slots = []
        slot_keys = sorted(ship_abilities.keys(), key=lambda x: int(re.search(r'\d+', x).group()) if re.search(r'\d+', x) else 0)

        for slot_key in slot_keys:
            slot_data = ship_abilities[slot_key]
            abils = slot_data.get("abils", [])
            slot_options = []
            for abil_pair in abils:
                if isinstance(abil_pair, list) and len(abil_pair) >= 2:
                    type_id = abil_pair[0].upper()
                    name_zh = self.ability_name_map.get(type_id) or \
                              self.ability_name_map.get(type_id.replace("PREMIUM", "").strip("_")) or type_id
                    slot_options.append(f"{name_zh} [{abil_pair[1]}]")
            if slot_options:
                num = slot_data.get('slot', slot_key.replace("AbilitySlot", ""))
                ability_slots.append(f"  槽位 {num}: {' / '.join(slot_options)}")

        if ability_slots:
            display_area.insert(tk.END, "消耗品: \n" + "\n".join(ability_slots) + "\n\n")

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

            # 2. 船体处理
            if current_cat == "Hull":
                conceal_coeff = 0.81 if raw_level >= 8 else 0.9
                raw_vis_sea = module_data.get("visibilityFactor", 0)
                raw_vis_plane = module_data.get("visibilityFactorByPlane", 0)
                hull_info = {
                    "health": module_data.get("health"),
                    "maxSpeed": module_data.get("maxSpeed"),
                    "turningRadius": module_data.get("turningRadius"),
                    "visibilityFactor": raw_vis_sea,
                    "visibilityFactorByPlane": raw_vis_plane,
                    "calc_vis_sea": round(raw_vis_sea * conceal_coeff, 2),
                    "calc_vis_plane": round(raw_vis_plane * conceal_coeff, 2)
                }
                for letter in target_letters:
                    combined_stats[letter]["Hull"] = [hull_info]

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
                            label = self.BUFF_MAP.get(mk, mk)
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

                        # 既然炮座里没数据，直接取防空圈本身的基础伤害
                        net_dmg = sv.get("areaDamage", 0)

                        info = {
                            "id": sk,
                            "name": display_name,
                            "is_aura": True,
                            "is_bubble_layer": is_bubble_layer,
                            "min_dist": sv.get("minDistance", 0),
                            "max_dist": sv.get("maxDistance", 0),
                            "net_dmg": round(net_dmg, 2),  # 记录本圈原始净秒伤
                            "dmg": round(net_dmg, 2),  # 初始化总秒伤
                            "hit_chance": sv.get("hitChance", 0),
                            "bubble_dmg": sv.get("bubbleDamage", 0),
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
        # 防空秒伤
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
            if config["Hull"]:
                h = config["Hull"][0]
                display_area.insert(tk.END, f"  基础血量: {h['health']}\n  基础最大航速: {h['maxSpeed']} kt\n  转向半径: {h['turningRadius']} m\n")
                display_area.insert(tk.END, f"  隐蔽: \n    对海隐蔽: {h['visibilityFactor']} km (最小: {h['calc_vis_sea']} km)\n")
                display_area.insert(tk.END, f"    对空隐蔽: {h['visibilityFactorByPlane']} km (最小: {h['calc_vis_plane']} km)\n")
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
                        planes_str = " / ".join(item.get("planes", []))
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
                    "asw": "空袭"
                }
                for as_conf in as_items:
                    u_type = as_conf['ui_type']
                    label = ui_map.get(u_type, u_type.capitalize())

                    # 处理 Infinity 情况
                    max_d = as_conf['max_dist']
                    dist_str = f"{as_conf['min_dist']}-{max_d}m" if str(
                        max_d).lower() != 'inf' and max_d < 999999 else "全图范围"

                    display_area.insert(tk.END, f"    - [{label}] 型号: {as_conf['plane_id']}\n")
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
                            label = "远程" if a['max_dist'] > 4500 else "中程" if a['max_dist'] > 2500 else "近程"
                            display_area.insert(tk.END,
                                                f"      - {label}-{a['name']}:\n        射程: {a['min_dist']}-{a['max_dist']}m | areaDamage: {a['dmg']} | 命中率: {int(a['hit_chance'] * 100)}%\n")

                    # 2. 渲染黑云
                    bubble_layers = [a for a in sorted_items if a.get('is_bubble_layer')]
                    if bubble_layers:
                        display_area.insert(tk.END, "    [爆炸属性]:\n")
                        for b in bubble_layers:
                            display_area.insert(tk.END,
                                                f"      - {b['name']}:\n        射程: {b['min_dist']}-{b['max_dist']}m | bubbleDamage: {b['bubble_dmg']} | 数量: {b['bubbles']} 朵\n")

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

                    for (name, barrels, reload_val, ammo, iR, mR, iD, rz, rd, rm, dl), count in wp_counts.items():
                        if ammo:
                            # 这里的 ammo 是一个 tuple (来自上面 wp_counts 的 key)
                            # 调用你之前定义的专门处理弹药列表翻译的方法
                            translated_ammo_list = []
                            for aid in ammo:
                                clean_id = aid.replace("IDS_", "").upper().strip()
                                # 依次从弹药表、武器表查询，找不到则显示原 ID
                                a_name = self.ammo_name_mapping.get(clean_id) or \
                                         self.gun_name_mapping.get(clean_id) or \
                                         aid
                                translated_ammo_list.append(a_name)
                            ammo_str = " / ".join(translated_ammo_list)
                        else:
                            ammo_str = "无"
                        temp_data = {
                            "idealRadius": iR,  # 这里需要确保 key 匹配
                            "minRadius": mR,
                            "idealDistance": iD
                        }
                        h_formula = self.get_dispersion_formula(temp_data)

                        if cat_key == "Torpedoes":
                            # 鱼雷不显示公式和纵向系数，显示型号和装填
                            display_area.insert(tk.END,f"    - 鱼雷发射管: {name} x{count}: {barrels:.0f}联装, 装填: {reload_val}s, 弹药: {ammo_str}\n")
                        elif cat_key == "DepthChargeGuns":
                            # 深弹：只显示基础信息，不显示散布和系数
                            display_area.insert(tk.END,
                                                f"    - 深水炸弹: {name} x{count}: {barrels:.0f}联装, 装填: {reload_val}s, 弹药: {ammo_str}\n")
                        else:
                            display_area.insert(tk.END,f"    - 炮塔: {name} x{count}: {barrels:.0f}联装, 装填: {reload_val}s, 弹药: {ammo_str}\n")
                            display_area.insert(tk.END,f"      - 横向散布公式: {h_formula}\n")
                            display_area.insert(tk.END,f"      - 纵向散步系数: {rz} ~ {rd}(R={dl * 100:.0f}%) ~ {rm}\n")

                display_area.insert(tk.END, "-" * 40 + "\n\n")