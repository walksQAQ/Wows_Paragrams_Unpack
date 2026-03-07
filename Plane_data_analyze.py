import json
import os
import sys
import tkinter as tk

from NameMapping import Mapping as NameMapping

class PlaneDataAnalyzer:
    def __init__(self, log_func=None):
        # 1. 自动获取基础路径（支持打包后的 exe 和 源代码路径）
        if getattr(sys, 'frozen', False):
            self.base_dir = os.path.dirname(sys.executable)
        else:
            self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.log_func = log_func  # 核心：保存 UI 传入的日志函数
        self.ability_name_map = {}
        self.plane_name_mapping = {}
        self.ammo_name_mapping = {}

    def _log(self, message):
        """内部调用的日志工具"""
        if self.log_func:
            self.log_func(message)  # 如果有回调，发给 UI
        else:
            print(message)  # 否则打印到控制台

    def initialize_mapping(self):
        self.load_plane_name_mapping()
        self.load_ability_name_map()
        self.load_ammo_name_mapping()
        self._log("飞机解析器映射表已同步")

    def load_ability_name_map(self):
        file_path = os.path.join(self.base_dir, "data", "consumable_names.json")
        try:
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    raw_json = json.load(f)
                    self.ability_name_map = {k.upper(): v for k, v in raw_json.items()}
        except Exception as e:
            self.log_func(f"读取技能映射出错: {e}")

    def load_plane_name_mapping(self):
        plane_json_path = os.path.join(self.base_dir, "data", "plane_names.json")
        if os.path.exists(plane_json_path):
            try:
                with open(plane_json_path, 'r', encoding='utf-8') as f:
                    self.plane_name_mapping = json.load(f)
            except Exception as e:
                self.log_func(f"加载飞机翻译失败: {e}")

    def load_ammo_name_mapping(self):
        """加载由 POToolKit 生成的弹药翻译字典"""
        # 路径指向 POToolkit 生成的 ammo_names.json
        ammo_json_path = os.path.join(self.base_dir, "data", "ammo_names.json")
        if os.path.exists(ammo_json_path):
            try:
                with open(ammo_json_path, 'r', encoding='utf-8') as f:
                    self.ammo_name_mapping = json.load(f)
            except Exception as e:
                self.log_func(f"加载弹药翻译失败: {e}")

    def analyze(self, display_area, data):
        """主入口：解析机载设备 JSON 并渲染至 UI"""
        # 1. 身份识别
        idx = data.get("index", "Unknown")
        raw_name = data.get("name", idx)
        display_name = self.plane_name_mapping.get(raw_name.upper(), raw_name)

        # 处理 typeinfo
        typeinfo = data.get("typeinfo", {})
        nation = typeinfo.get("nation", "Unknown")
        species = typeinfo.get("species", "Aircraft")  # 如 Bomber, TorpedoBomber
        species_name = NameMapping.AIRCRAFT_CLASS_MAP.get(species, species)

        # 2. 核心性能提取
        level = data.get("level", 0)
        squad_size = data.get("numPlanesInSquadron", 0)
        attack_size = data.get("attackerSize", 0)
        hp = data.get("maxHealth", 0)

        # 航速换算公式: Raw * 5.25 / 15
        raw_speed = data.get("speedMoveWithBomb", 0)
        knots = round(raw_speed * 5.25 / 15, 1)

        # 3. 渲染至 UI
        display_area.insert(tk.END, f"飞机型号: {display_name}\n")
        display_area.insert(tk.END, f"等级: {level}\n"
                                    f"编号: {idx}\n"
                                    f"国籍: {nation}\n"
                                    f"机种: {species_name}\n")
        display_area.insert(tk.END, "-" * 30 + "\n")

        # --- 生存与机动模块 ---
        display_area.insert(tk.END, "[飞行性能]\n")
        display_area.insert(tk.END, f"  - 巡航航速: {knots} kts\n")
        display_area.insert(tk.END, f"  - 单机生命值: {hp}\n")
        display_area.insert(tk.END, f"  - 全中队血量: {int(hp * squad_size)}\n")

        # 整备逻辑
        hangar = data.get("hangarSettings", {})
        if hangar:
            restore = hangar.get("timeToRestore", 0)
            max_val = hangar.get("maxValue", 0)
            display_area.insert(tk.END, f"  - 整备时间: {restore}s / 架\n")
            display_area.insert(tk.END, f"  - 甲板容量: {max_val} 架\n")

        # --- 攻击组模块 ---
        display_area.insert(tk.END, "\n[编队与攻击]\n")
        display_area.insert(tk.END, f"  - 中队编制: {squad_size} 架\n")
        display_area.insert(tk.END, f"  - 攻击规模: {attack_size} 架 x {data.get('attackCount', 1)} 轮\n")
        display_area.insert(tk.END, f"  - 投弹延迟: {data.get('bombingDropPointTime', 0)}s\n")
        display_area.insert(tk.END,
                            f"  - 准备/瞄准时间: {data.get('preparationTime', 0)}s / {data.get('aimingTime', 0)}s\n")

        # --- 消耗品模块 (Slot 循环) ---
        self._parse_abilities(display_area, data.get("PlaneAbilities", {}))

        # --- 弹药关联提示 ---
        bomb_id = data.get("bombName", "")
        bomb_name = self.ammo_name_mapping.get(bomb_id.upper(),bomb_id)
        if bomb_id:
            display_area.insert(tk.END, f"\n  - 关联弹药: {bomb_name}({bomb_id})\n")

        display_area.insert(tk.END, "\n" + "=" * 45 + "\n\n")

    def _parse_abilities(self, display_area, abilities_dict):
        """解析飞机技能插槽"""
        # 增加类型检查，防止 abilities_dict 是 None 或 非字典
        if not isinstance(abilities_dict, dict) or not abilities_dict:
            return

        display_area.insert(tk.END, "\n[机载消耗品]\n")

        try:
            # 过滤并排序 Slot 键名
            slots = [k for k in abilities_dict.keys() if "AbilitySlot" in k]
            for slot_key in sorted(slots, key=lambda x: int(''.join(filter(str.isdigit, x)) or 0)):
                slot_data = abilities_dict[slot_key]
                if not isinstance(slot_data, dict): continue

                abils = slot_data.get("abils", [])
                if not abils: continue

                for item in abils:
                    if isinstance(item, list) and len(item) > 0:
                        abil_id = item[0]
                        limit = item[1] if len(item) > 1 else "Unknown"

                        # --- 关键修正点：使用变量 self.ability_name_map 而不是方法名 ---
                        name = self.ability_name_map.get(abil_id.upper(), abil_id)

                        slot_num = slot_data.get('slot', 0) + 1
                        display_area.insert(tk.END, f"  - 插槽 {slot_num}: {name} ({limit})\n")
        except Exception as e:
            self._log(f"解析消耗品插槽时出错: {e}")