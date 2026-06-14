"""
ShipAnalyzer —— 舰船数据分析器。

继承 BaseAnalyzer，将 Ship_data_analyze.py 迁移到新架构。
analyze() 返回 AnalysisResult，不再直接操作 UI。
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Callable, Optional

from analyzers.base_analyzer import BaseAnalyzer
from models.analysis_result import AnalysisResult, DataSection, DataItem
from utils.path_utils import get_split_dir, get_data_dir


class TextCollector:
    """
    文字收集器 —— 替代 tk.Text.insert()。

    旧代码大量使用 display_area.insert(tk.END, ...) 直接写 UI。
    迁移时将所有文本收集到此对象中，然后统一包装为 AnalysisResult。
    """

    def __init__(self):
        self._lines: list[str] = []

    def write(self, text: str) -> None:
        """替代 display_area.insert(tk.END, text)"""
        self._lines.append(text.rstrip("\n"))

    def writeln(self, text: str = "") -> None:
        self._lines.append(text)

    def result(self, title: str, subtitle: str = "") -> AnalysisResult:
        """将收集的文本打包成 AnalysisResult"""
        items: list[DataItem] = []
        for line in self._lines:
            if line.strip():
                items.append(DataItem(name=line, value=""))
            elif line == "":
                items.append(DataItem(name="", value=""))
        return AnalysisResult(
            title=title, subtitle=subtitle,
            sections=[DataSection(label=title, items=items)]
        )


class ShipAnalyzer(BaseAnalyzer):
    """舰船数据分析器"""

    # ── 正则模式（从旧代码完整继承）──
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
        "AirDefense": re.compile(r'(HP_[A-Z]GA_\d+|HP_[A-Z]GM_\d+_HP_[A-Z]GA_\d+|Aura_\d+|(Far|Medium|Near)\d*(_Bubbles)?)'),
        "Torpedoes": re.compile(r'HP_[A-Z]GT_\d+'),
        "DepthChargeGuns": re.compile(r"HP_[A-Z]GB_\d+"),
    }

    @staticmethod
    def _dispersion_formula(ir, mr, id_dist):
        """横向散布公式: (IR-MR)/(ID/1000) * R + MR*30"""
        if not all(v is not None and v != 0 for v in [ir, mr, id_dist]):
            return None
        slope = (ir - mr) / (id_dist / 1000)
        intercept = mr * 30
        return f"{slope:.2f}R + {intercept:.2f}"

    @staticmethod
    def _fmt_val(v, fmt: str | None = None) -> str:
        """格式化显示值：按 fmt 取整、布尔转中文"""
        if fmt == "bool":
            return "是" if v else "否"
        if fmt and isinstance(v, (int, float)):
            try:
                return f"{v:{fmt}}"
            except (ValueError, TypeError):
                pass
        if isinstance(v, bool):
            return "是" if v else "否"
        if isinstance(v, float):
            if v == int(v):
                return str(int(v))
            return f"{v:.2f}"
        return str(v)

    def __init__(self, log_func: Optional[Callable[[str], None]] = None):
        super().__init__(log_func)
        # 映射表
        self.ship_name_mapping: dict = {}
        self.ability_name_map: dict = {}
        self.rage_name_mapping: dict = {}
        self.gun_name_mapping: dict = {}
        self.ammo_name_mapping: dict = {}
        self.plane_name_mapping: dict = {}
        self._cached_mod_data: dict = {}
        # 消耗品配置文件注册表（替代旧的 ShipConsumableDataAnalyze）
        self._ability_registry: dict[str, dict] = {}

    def _load_ability_registry(self) -> None:
        """加载 data/split/Ability/ 下所有消耗品配置文件"""
        import json
        ability_dir = get_split_dir() / "Ability"
        if not ability_dir.exists():
            return
        for f in ability_dir.iterdir():
            if f.suffix.lower() == ".json":
                try:
                    self._ability_registry[f.stem] = json.loads(f.read_text(encoding="utf-8"))
                except Exception as e:
                    self._log(f"加载能力文件 {f.name} 失败: {e}")

    def _get_consumable_config(self, file_key: str, config_key: str) -> dict:
        """从注册表查询消耗品配置"""
        configs = self._ability_registry.get(file_key, {})
        return configs.get(config_key) or configs.get("Default", {})

    # ── 映射表初始化 ──────────────────────────────────────

    def initialize_mapping(self) -> None:
        """加载所有 JSON 映射表"""
        self.ship_name_mapping = self.load_json_mapping("ship_names.json")
        raw = self.load_json_mapping("consumable_names.json")
        self.ability_name_map = {k.upper(): v for k, v in raw.items()}
        self.rage_name_mapping = self.load_json_mapping("rage_mode_names.json")
        self.gun_name_mapping = self.load_json_mapping("guns_names.json")
        raw_ammo = self.load_json_mapping("ammo_names.json")
        self.ammo_name_mapping = {k.upper(): v for k, v in raw_ammo.items()}
        self.plane_name_mapping = self.load_json_mapping("plane_names.json")
        self._load_ability_registry()
        self._log("ShipAnalyzer 映射表已同步")

    # ── 名称查询 ──────────────────────────────────────────

    def get_localized_weapon_name(self, raw_id: str) -> str:
        if not raw_id:
            return "Unknown"
        clean_id = raw_id.replace("IDS_", "").upper()
        if clean_id in self.gun_name_mapping:
            return self.gun_name_mapping[clean_id]
        for k, v in self.gun_name_mapping.items():
            if k.upper() == clean_id:
                return v
        return raw_id

    def get_localized_plane_name(self, raw_id: str) -> str:
        if not raw_id:
            return "Unknown"
        clean_id = raw_id.replace("IDS_", "").upper().strip()
        table = self.plane_name_mapping or {}
        if clean_id in table:
            return table[clean_id]
        for k, v in table.items():
            if k.upper() == clean_id:
                return v
        return raw_id

    # ── 辅助方法 ──────────────────────────────────────────

    def get_dispersion_formula(self, weapon_data: dict) -> str:
        ir = weapon_data.get('idealRadius')
        mr = weapon_data.get('minRadius')
        id_dist = weapon_data.get('idealDistance')
        if ir is None or mr is None or id_dist is None:
            return "数据缺失"
        slope = (ir - mr) / (id_dist / 1000)
        intercept = mr * 30
        return f"{round(slope, 2):.1f}R + {round(intercept, 2):.0f}"

    def load_mod_file(self, mod_filename: str) -> dict:
        if mod_filename in self._cached_mod_data:
            return self._cached_mod_data[mod_filename]
        json_path = get_split_dir() / "Modernization" / f"{mod_filename}.json"
        if json_path.exists():
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._cached_mod_data[mod_filename] = data
                    return data
            except Exception as e:
                self._log(f"加载插件文件 {mod_filename} 失败: {e}")
        return {}

    def get_conceal_coeff(self, species: str, level: int, nation: str, ship_index: str) -> float:
        mod_data = self.load_mod_file("PCM027_ConcealmentMeasures_Mod_I")
        if species == "Submarine":
            skill_bonus = 1.0
        elif species == "AirCarrier":
            skill_bonus = 0.85
        else:
            skill_bonus = 0.9
        mod_ships = mod_data.get("ships", [])
        mod_excludes = mod_data.get("excludes", [])
        mod_levels = mod_data.get("shiplevel", [])
        mod_types = mod_data.get("shiptype", [])
        mod_nations = mod_data.get("nation", [])
        upgrade_bonus = 1.0
        is_whitelisted = any(s.startswith(ship_index) for s in mod_ships)
        is_excluded = any(ex.startswith(ship_index) for ex in mod_excludes)
        if is_whitelisted:
            upgrade_bonus = 0.9
        elif not is_excluded and (level in mod_levels and species in mod_types and nation in mod_nations):
            upgrade_bonus = 0.9
        return skill_bonus * upgrade_bonus

    def analyze_ship_data(self, ship_data: dict) -> dict:
        """分析船体模块 — inline 替代旧的 ShipHullDataAnalyze"""
        all_hulls = {}

        def _analyze_hull(hull_data: dict, hull_id: str) -> dict:
            cit_module = hull_data.get("Cit", {})
            has_cit = bool(cit_module)
            sub_battery = hull_data.get("SubmarineBattery", {})
            has_battery = bool(sub_battery)
            hydrophone = hull_data.get("Hydrophone", {})
            has_hydrophone = bool(hydrophone)
            buoyancy = hull_data.get("buoyancyStates", {})
            buoyancy_data = []
            for state, values in buoyancy.items():
                if isinstance(values, (list, tuple)):
                    buoyancy_data.append({"state": state, "depth_range": values[0], "speed_multiplier": values[1]})

            return {
                "default_data": {
                    "label": "通用数据",
                    "items": {
                        "health": {"name": "基础血量", "val": hull_data.get("health"), "unit": "",     "fmt": ".0f", "order": 0},
                        "maxSpeed": {"name": "最大航速", "val": hull_data.get("maxSpeed"), "unit": "kts","fmt": ".1f", "order": 1},
                        "turningRadius": {"name": "转弯半径", "val": hull_data.get("turningRadius"), "unit": "m", "fmt": ".0f", "order": 2},
                        "rudderTime": {"name": "转舵时间", "val": hull_data.get("rudderTime", 0) * 0.77, "unit": "s", "fmt": ".1f", "order": 3},
                        "vis_sea": {"name": "水面隐蔽", "val": hull_data.get("visibilityFactor"), "unit": "km", "fmt": ".2f", "order": 4},
                        "vis_plane": {"name": "空中隐蔽", "val": hull_data.get("visibilityFactorByPlane"), "unit": "km", "fmt": ".2f", "order": 5},
                        "has_cit": {"name": "是否有核心区模块", "val": has_cit, "unit": "", "fmt": "bool", "order": 6},
                        "hull_regenper": {"name": "船体回复率", "val": hull_data.get("Hull", {}).get("regeneratedHPPart"), "unit": "", "fmt": ".0%", "order": 7},
                        "cit_regenper": {"name": "核心回复率", "val": hull_data.get("Cit", {}).get("regeneratedHPPart"), "unit": "", "fmt": ".0%", "order": 8},
                        "engine_power": {"name": "引擎马力", "val": hull_data.get("enginePower"), "unit": "HP","fmt": ".0f", "order": 9},
                    }
                },
                "submarine_sp_data": {
                    "label": "潜艇特殊数据",
                    "items": {
                        "has_battery": {"name": "潜艇电力", "val": has_battery, "unit": "", "fmt": "bool", "order": 0},
                        "bat_cap": {"name": "电池容量", "val": sub_battery.get("capacity"), "unit": "", "fmt": ".0f", "order": 1},
                        "bat_regen": {"name": "电力恢复", "val": sub_battery.get("regenRate"), "unit": "/s", "fmt": ".2f", "order": 2},
                        "has_hydrophone": {"name": "水听器", "val": has_hydrophone, "unit": "", "fmt": "bool", "order": 3},
                        "hp_radius": {"name": "水听器范围", "val": hydrophone.get("waveRadius")/1000, "unit": "km", "fmt": ".2f", "order": 4},
                        "hp_frep": {"name": "水听器更新周期", "val": hydrophone.get("updateFrequency"), "unit": "s", "fmt": ".1f", "order": 5},
                        "hp_work_states": {"name": "水听器工作深度", "val": hydrophone.get("workingBuoyancyStates"), "unit": "", "fmt": ".0f", "order": 6},
                        "hp_detect_states": {"name": "水听器可探测深度", "val": hydrophone.get("detectableBuoyancyStates"), "unit": "", "fmt": ".0f", "order": 7},
                        "buoyancyStates": {"name": "深度等级数据", "val": buoyancy_data, "unit": "", "fmt": ".0f", "order": 8},
                        "buoyancy_rudder_time": {"name": "水平舵转舵时间", "val": hull_data.get("buoyancyRudderTime", 0) * 0.77, "unit": "s", "fmt": ".1f", "order": 9},
                        "buoyancy_speed": {"name": "上浮/下潜速度", "val": hull_data.get("maxBuoyancySpeed"), "unit": "m/s", "fmt": ".2f", "order": 10},
                    }
                }
            }

        for mod_key, module_data in ship_data.items():
            if not isinstance(module_data, dict):
                continue
            hull_id = None
            if self.DEFAULTS["Hull"].search(mod_key) or mod_key == "Hull_A":
                hull_id = "A"
                save_key = "A_Hull"
            else:
                match = self.PATTERNS["Hull"].match(mod_key) or self.PATTERNS_NEW["Hull"].match(mod_key)
                if match:
                    hull_id = match.group(1)
                    save_key = mod_key
            if hull_id:
                try:
                    all_hulls[save_key] = _analyze_hull(module_data, hull_id)
                except Exception as e:
                    self._log(f"解析 {mod_key} 失败: {e}")
        return all_hulls

    def _format_consumable_details(self, info: dict) -> list[str]:
        """格式化消耗品详情（返回文本行列表）"""
        from models.name_mapping import Mapping as NameMapping
        output = []
        isAutoConsumable = "是" if info.get('isAutoConsumable') else "否"
        isInterceptor = "是" if info.get('isInterceptor') else "否"

        t = info.get('type', '')
        if t == "crashCrew":
            output.append("扑灭起火、清除进水、并修复受损配件。阻止敌方潜艇发射的鱼雷进行导向。")
        elif t == "regenCrew":
            v = info.get('regenHPSpeed', 0)
            output.append(f"每秒回复血量: {'+' if v > 0 else ''}{v * 100}%")
        elif t == "airDefenseDisp":
            v1 = info.get('areaDmgMultiplier', 0)
            v2 = info.get('bubbleDmgMultiplier', 0)
            output.append(f"防空区域秒伤: {'+' if v1 > 0 else ''}{v1 * 100:.2f}%")
            output.append(f"黑云伤害: {'+' if v2 > 0 else ''}{v2 * 100:.2f}%")
        elif t == "fighter":
            raw_name = info.get('fighterName', '未知')
            display_name = self.plane_name_mapping.get(raw_name.upper(), raw_name)
            output.append(f"战斗机名称: {display_name}")
            output.append(f"战斗机数量: {info.get('fighterNum', 0)}")
            output.append(f"是否为截击机: {isInterceptor}")
            output.append(f"狗斗时间: {info.get('dogFightTime', 0)}s")
            output.append(f"离开时间: {info.get('flyAwayTime', 0)}s")
            output.append(f"战斗机爬升角度: {info.get('flightClimbAngle', 0)}°")
            output.append(f"巡逻半径: {info.get('radiusToKill', 0) / 10}km")
            output.append(f"索敌时间: {info.get('timeDelayAtk', 0)}s / 瞄准时间: {info.get('timeWaitDelayAtk', 0)}s")
        elif t == "scout":
            dc = info.get('gunsDistCoeff', 0) - 1
            output.append(f"主炮射程 {'+' if dc > 0 else ''}{dc * 100:.2f}%")
        elif t == "smokeGenerator":
            output.append(f"烟雾生成半径: {info.get('radius', 0) * 3}m")
            output.append(f"烟雾生成高度: {info.get('height', 0)}m")
            output.append(f"烟雾生成速度限制: {info.get('speedLimit', 0)}kts")
            output.append(f"烟雾扩散时间: {info.get('lifeTime', 0)}s")
        elif t == "speedBoosters":
            output.append(f"最高航速: {'+' if info.get('boostCoeff', 0) > 0 else ''}{info['boostCoeff'] * 100}%")
            output.append(f"推力加成: 前进{'+' if info.get('forwardEngForsag', 0) > 0 else ''}{info['forwardEngForsag'] * 100}% / 后退{'+' if info.get('backwardEngForsag', 0) > 0 else ''}{info['backwardEngForsag'] * 100}%")
            output.append(f"加速最大速度倍率: 前进{info.get('forwardEngForsagMaxSpd', 0) * 100}% / 后退{info.get('backwardEngForsagMaxSpd', 0) * 100}%")
        elif t == "sonar":
            output.append(f"舰船探测距离: {info.get('distShip', 0) * 0.03:.2f} km")
            output.append(f"鱼雷探测距离: {info.get('distTorpedo', 0) * 0.03:.2f} km")
            output.append(f"水雷探测距离: {info.get('distMine', 0) * 0.03:.2f} km")
        elif t == "torpedoReloader":
            output.append(f"鱼雷装填时间: {info.get('torpedoReloadTime', 0)}s")
        elif t == "rls":
            classes = info.get("affectedClasses", [])
            output.append(f"舰船探测距离: {info.get('distShip', 0) * 0.03:.2f} km")
            if classes:
                output.append(f"限制探测舰种: {', '.join(NameMapping.SHIP_CLASS_MAP.get(c, c) for c in classes)}")
        elif t == "artilleryBoosters":
            bc = info.get('boostCoeff', 0) - 1
            output.append(f"主炮装填时间: {'+' if bc > 0 else ''}{bc * 100:.2f}%")
        elif t == "healForsage":
            output.append(f"引擎冷却速度: {'+' if info.get('boostCoeff', 0) > 0 else ''}{info['boostCoeff'] * 100}%")
        elif t == "callFighters":
            raw_name = info.get('fighterName', '未知')
            display_name = self.plane_name_mapping.get(raw_name.upper(), raw_name)
            output.append(f"战斗机名称: {display_name}")
            output.append(f"战斗机数量: {info.get('fighterNum', 0)}")
            output.append(f"截击机: {isInterceptor}")
            output.append(f"狗斗时间: {info.get('dogFightTime', 0)}s")
            output.append(f"巡逻半径: {info.get('radiusToKill', 0) / 10}km")
            output.append(f"索敌时间: {info.get('timeDelayAtk', 0)}s / 瞄准时间: {info.get('timeWaitDelayAtk', 0)}s")
        elif t == "regenerateHealth":
            output.append("恢复飞机中队部分生命值。在敌方战斗机攻击时使用能免于被击毁。")
        elif t == "depthCharges":
            output.append(f"半径: {info.get('radius', 0) * 0.003:.2f}km")
        elif t == "hydrophone":
            output.append(f"虚影存留时间: {info.get('zoneLifeTime', 0)}s")
            output.append(f"刷新时间: {info.get('hpUpdFreq', 0)}s")
            output.append(f"视野距离: {info.get('hpWaveRadius', 0) * 0.001:.2f}km")
        elif t == "fastRudders":
            brt = info.get('buoyancyRudderTimeCoeff', 0) - 1
            bsc = info.get('maxBuoyancySpeedCoeff', 0) - 1
            output.append(f"水平舵换挡时间: {'+' if brt > 0 else ''}{brt * 100:.2f}%")
            output.append(f"上浮/下潜速度: {'+' if bsc > 0 else ''}{bsc * 100:.2f}%")
        elif t == "subsEnergyFreeze":
            output.append("启用此消耗品后，下潜能力将停止消耗。")
            output.append(f"可在电池耗尽时启用: {'是' if info.get('canUseOnEmpty') else '否'}")
        elif t == "submarineLocator":
            output.append(f"舰船探测距离: {info.get('distShip', 0) * 0.03:.2f} km")
        elif t == "planeSmokeGenerator":
            output.append(f"烟雾生效延迟: {info.get('activationDelay', 0)}s")
            output.append(f"烟雾生成半径: {info.get('radius', 0) * 3}m")
            output.append(f"烟雾扩散时间: {info.get('lifeTime', 0)}s")
        elif t == "vampireDamage":
            output.append(f"用于恢复生命值的伤害转化系数: {info.get('damageGMHealCoeff', 0) * 100:.2f}%")
        elif t == "supportBuoy":
            output.append(f"加成区域: {info.get('battleDropVisualName', '')}")
            output.append(f"区域布置时间: {info.get('battleDropActTime', 0)}s")
            output.append(f"区域持续时间: {info.get('supportBuoyZoneLifetime', 0)}s")
            output.append(f"区域半径: {info.get('buffZoneRadius', 0) / 1000:.2f}km")
            output.append(f"效果持续时间: {info.get('buffDuration', 0)}s")
        return output

    def parse_rage_mode_advanced(self, rage_data: dict, current_species: str) -> list[str]:
        """解析战斗指令"""
        from models.name_mapping import Mapping as NameMapping
        info = []
        raw_name_upper = str(rage_data.get("rageModeName", "Unknown")).upper()
        base_msgid = f"IDS_DOCK_RAGE_MODE_TITLE_{raw_name_upper}"
        display_name = self.rage_name_mapping.get(base_msgid, raw_name_upper)
        info.append(f"=== 战斗指令: {display_name} ===")
        boost = rage_data.get("boostDuration", 0)
        info.append(f"  [基础属性]")
        info.append(f"    - 持续时间: {boost}s")
        max_act = rage_data.get("maxActivationCount", -1)
        info.append(f"    - 最大激活次数: {'无限' if max_act == -1 else f'{max_act} 次'}")
        info.append(f"    - 自动激活: {'是' if rage_data.get('isAutoUsage') else '否'}")
        info.append(f"    - 常驻生效: {'是' if rage_data.get('isModifierWorksAlways') else '否'}")
        delay = rage_data.get("decrementDelay", 0)
        if delay > 0:
            info.append(f"  [衰减逻辑]")
            info.append(f"    - 衰减倒计时: {delay}s")
            info.append(f"    - 衰减周期: {rage_data.get('decrementPeriod', 1)}s")
            info.append(f"    - 衰减数值: {rage_data.get('decrementCount', 0)}%")

        # ── 触发器和动作 ──
        TRIGGER_LABELS = {
            "GameLogicTriggerOnActivation": "触发效果",
            "GameLogicTriggerProgress": "进度积累",
            "GameLogicTrigger": "进度积累",
        }
        for key, trigger in rage_data.items():
            if "Trigger" in key and isinstance(trigger, dict):
                trigger_label = TRIGGER_LABELS.get(key, key)
                info.append(f"  [{trigger_label}]")

                # 激活条件
                act = trigger.get("Activator", {})
                if act:
                    atype = act.get("type", "Unknown")
                    info.append(f"    激活: {atype}")
                    for k, v in act.items():
                        if k == "type":
                            continue
                        elif k == "subRibbons" and isinstance(v, list):
                            names = [NameMapping.RIBBON_MAP.get(str(rid), f"未知勋带({rid})") for rid in v]
                            info.append(f"    - 所需勋带: {', '.join(names)}")
                        elif k == "requiredCount":
                            info.append(f"    - 所需次数: {v}")
                        elif k == "separateTracking":
                            info.append(f"    - 独立追踪: {'是' if v else '否'}")
                        elif k == "stateName":
                            info.append(f"    - 状态: {v}")
                        else:
                            unit = "m" if k == "radius" else ""
                            label = NameMapping.DETAIL_MAP.get(k, k)
                            info.append(f"    - {label}: {v} {unit}")

                # 执行动作
                actions_found = {k: v for k, v in trigger.items() if k.startswith("Action") and isinstance(v, dict)}
                if actions_found:
                    for action_key, aln in actions_found.items():
                        atype = aln.get("type", "Unknown")
                        info.append(f"    动作: {atype}")
                        for k, v in aln.items():
                            if k == "type":
                                continue
                            if k in ["planeId", "planeName"]:
                                info.append(f"    - 飞机型号: {self.get_localized_plane_name(v)}")
                            elif k == "progressName":
                                info.append(f"    - 进度标识: {v}")
                            else:
                                label = NameMapping.DETAIL_MAP.get(k, k)
                                unit = "s" if k in ["reduceTime", "workTime"] else ""
                                info.append(f"    - {label}: {v}{unit}")

        # ── 加成效果 ──
        mods = rage_data.get("modifiers", {})
        if mods:
            info.append(f"  [加成效果]")
            for k, v in mods.items():
                label = NameMapping.MODIFIER_MAP.get(k, k)
                if isinstance(v, dict):
                    factor = v.get(current_species)
                    if factor is not None:
                        info.append(f"    - {NameMapping.SHIP_CLASS_MAP.get(current_species, current_species)}: {round((factor - 1.0) * 100):+.0f}%")
                elif k == "healthRegen":
                    info.append(f"    - {label}: 每秒回复 {v:.0f} HP")
                elif isinstance(v, (float, int)):
                    if v > 10.0:
                        info.append(f"    - {label}: +{v:.0f}")
                    else:
                        info.append(f"    - {label}: {round((v - 1.0) * 100):+.0f}%")
                else:
                    info.append(f"    - {label}: {v}")
        return info

    # ── 主分析入口 ────────────────────────────────────────

    def analyze(self, raw_data: dict) -> AnalysisResult:
        """
        分析舰船数据，返回 AnalysisResult。

        此方法是旧 ShipDataAnalyzer.analyze() 的迁移版本。
        将所有 display_area.insert() 替换为 TextCollector.write() / writeln()。
        """
        from models.name_mapping import Mapping as NameMapping
        t = TextCollector()

        hulls_info = self.analyze_ship_data(raw_data)
        ship_index = raw_data.get("index", "Unknown")
        ship_id = raw_data.get("id", "N/A")

        # ── 舰船名称映射 ──────────────────────────────────
        raw_key = str(ship_index).upper().replace("IDS_", "").strip()
        real_name = self.ship_name_mapping.get(raw_key)
        if not real_name and "_" in raw_key:
            real_name = self.ship_name_mapping.get(raw_key.split("_")[0])
        real_name = real_name or ship_index

        type_info = raw_data.get("typeinfo", {})
        raw_nation = type_info.get("nation", "Unknown")
        raw_species = type_info.get("species", "Unknown")
        raw_group = raw_data.get("group", "standard")
        raw_level = raw_data.get("level", 0)

        # ── 父级/原型舰 ────────────────────────────────────
        raw_parent_ship = str(raw_data.get("parentShip", "")).strip()
        if raw_parent_ship:
            parent_ship_index = raw_parent_ship.split("_")[0].replace("IDS_", "").strip().upper()
            parent_ship_name = self.ship_name_mapping.get(parent_ship_index, parent_ship_index)
        else:
            parent_ship_name = ""
        raw_origin_ship = str(raw_data.get("originShipName", "")).strip()
        if raw_origin_ship:
            origin_ship_index = raw_origin_ship.split("_")[0].replace("IDS_", "").strip().upper()
            origin_ship_name = self.ship_name_mapping.get(origin_ship_index, origin_ship_index)
        else:
            origin_ship_name = ""

        # ── 最小隐蔽计算 ──────────────────────────────────
        conceal_coeff = self.get_conceal_coeff(raw_species, raw_level, raw_nation, ship_index)
        for hull_data in hulls_info.values():
            items = hull_data.get("default_data", {}).get("items", {})
            vis_sea = items.get("vis_sea", {})
            if vis_sea.get("val") is not None:
                items["vis_sea_min"] = {
                    "name": "水面隐蔽(最小)",
                    "val": vis_sea["val"] * conceal_coeff,
                    "unit": "km",
                    "fmt": ".2f",
                    "order": 4.1,
                }
            vis_plane = items.get("vis_plane", {})
            if vis_plane.get("val") is not None:
                items["vis_plane_min"] = {
                    "name": "空中隐蔽(最小)",
                    "val": vis_plane["val"] * conceal_coeff,
                    "unit": "km",
                    "fmt": ".2f",
                    "order": 5.1,
                }

        # ── 基础信息 ──────────────────────────────────────
        t.writeln(f"【基础属性】")
        t.writeln(f"  舰船名称: {real_name}")
        t.writeln(f"  编号: {ship_index}")
        t.writeln(f"  ID: {ship_id}")
        t.writeln(f"  国家: {NameMapping.NATION_MAP.get(raw_nation, raw_nation)}")
        t.writeln(f"  舰种: {NameMapping.SHIP_CLASS_MAP.get(raw_species, raw_species)}")
        t.writeln(f"  等级: {NameMapping.LEVEL_MAP[raw_level] if raw_level < len(NameMapping.LEVEL_MAP) else raw_level}")
        t.writeln(f"  状态: {NameMapping.SHIP_GROUP_MAP.get(raw_group, raw_group)}")
        if parent_ship_name:
            t.writeln(f"  原型舰船: {parent_ship_name}")
        if origin_ship_name:
            t.writeln(f"  原型舰船: {origin_ship_name}")
        t.writeln()

        # ── 船体数据 ──────────────────────────────────────
        t.writeln(f"【船体模块数据】")
        for hull_key in sorted(hulls_info.keys()):
            hull_data = hulls_info[hull_key]
            default_data = hull_data.get("default_data", {})
            items = default_data.get("items", {})
            # 提取船体字母标识：A_Hull_1929 → A,  A_Hull → A
            letter = hull_key.split("_")[0] if "_" in hull_key else hull_key
            t.writeln(f"  -- {letter} 船体 --")
            for key in sorted(items, key=lambda x: items[x].get("order", 0)):
                item = items[key]
                v = item["val"]
                if v is None:
                    v = "N/A"
                else:
                    fmt = item.get("fmt")
                    v = self._fmt_val(v, fmt)
                unit = item.get("unit", "")
                unit_str = f" {unit}" if unit else ""
                name = item["name"]
                t.writeln(f"    - {name}: {v}{unit_str}")
            # 潜艇特殊数据
            if raw_species == "Submarine":
                from models.name_mapping import Mapping as NameMapping
                sub_data = hull_data.get("submarine_sp_data", {})
                sub_items = sub_data.get("items", {})
                default_items = hull_data.get("default_data", {}).get("items", {})
                max_speed = default_items.get("maxSpeed", {}).get("val", 0) or 0

                t.writeln(f"  潜艇专有数据:")

                # 水平舵 + 上浮/下潜速度
                br_time = sub_items.get("buoyancy_rudder_time", {}).get("val", 0) or 0
                b_speed = sub_items.get("buoyancy_speed", {}).get("val", 0) or 0
                t.writeln(f"    - 基础水平舵换挡时间: {br_time:.2f} s")
                t.writeln(f"    - 最大上浮和下潜速度: {b_speed} m/s")

                # 最大水下航速（从深度数据中取 invul 速度倍率）
                buoyancy_list = sub_items.get("buoyancyStates", {}).get("val", []) or []
                invul_speed_multiplier = 1.0
                for entry in buoyancy_list:
                    if isinstance(entry, dict) and entry.get('state') == 'DEEP_WATER_INVUL':
                        invul_speed_multiplier = entry.get('speed_multiplier', 1.0)
                        break
                t.writeln(f"    - 最大水下航速: {max_speed * invul_speed_multiplier:.2f} kts")

                # 深度数据（固定顺序：水面→潜望镜→工作深度→最大深度）
                t.writeln(f"    - 深度数据:")
                b_map = {e['state']: e for e in buoyancy_list if isinstance(e, dict)}
                order = ["SURFACE", "PERISCOPE", "DEEP_WATER", "DEEP_WATER_INVUL"]
                for state_key in order:
                    if state_key in b_map:
                        data = b_map[state_key]
                        cn_name = NameMapping.DEPTH_MAP.get(state_key, state_key)
                        d_range = data.get('depth_range', [0, 0])
                        t.writeln(f"        ◈ [{cn_name}]: {d_range[0]:>5}m 至 {d_range[1]:>5}m")

                # 下潜能力（电池）
                has_battery = sub_items.get("has_battery", {}).get("val", False)
                if has_battery:
                    bat_cap = sub_items.get("bat_cap", {}).get("val", 0) or 0
                    bat_regen = sub_items.get("bat_regen", {}).get("val", 0) or 0
                    t.writeln(f"    - 下潜能力:")
                    t.writeln(f"      - 基础电池容量: {bat_cap}")
                    t.writeln(f"      - 基础电力恢复速度: {bat_regen} /s")

                # 水听器
                has_hydrophone = sub_items.get("has_hydrophone", {}).get("val", False)
                if has_hydrophone:
                    hp_radius = sub_items.get("hp_radius", {}).get("val", 0) or 0
                    hp_frep = sub_items.get("hp_frep", {}).get("val", 0) or 0
                    hp_work = sub_items.get("hp_work_states", {}).get("val", []) or []
                    hp_detect = sub_items.get("hp_detect_states", {}).get("val", []) or []
                    work_states = [NameMapping.DEPTH_MAP.get(s, s) for s in hp_work]
                    detect_states = [NameMapping.DEPTH_MAP.get(s, s) for s in hp_detect]
                    t.writeln(f"    - 水听器:")
                    t.writeln(f"      - 生效半径: {hp_radius} km")
                    t.writeln(f"      - 刷新周期: {hp_frep} s")
                    if work_states:
                        t.writeln(f"      - 水听器工作层级: {' / '.join(work_states)}")
                    if detect_states:
                        t.writeln(f"      - 可探测深度层级: {' / '.join(detect_states)}")
            t.writeln()

        # ── 消耗品数据 ────────────────────────────────────
        ship_abilities = raw_data.get("ShipAbilities", {})
        slot_keys = sorted(ship_abilities.keys(),
                           key=lambda x: int(re.search(r'\d+', x).group()) if re.search(r'\d+', x) else 0)

        if slot_keys:
            t.writeln(f"【消耗品数据】")
            prepared_consumable_data = []
            for slot_key in slot_keys:
                slot_data = ship_abilities[slot_key]
                abils = slot_data.get("abils", [])
                slot_items = []
                for abil_pair in abils:
                    if isinstance(abil_pair, list) and len(abil_pair) >= 2:
                        file_key = str(abil_pair[0]).strip()
                        config_key = str(abil_pair[1]).strip()
                        stats = self._get_consumable_config(file_key, config_key)
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
                            "buoyancyStates": stats.get("availableBuoyancyStates", []),
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
                            "timeWaitDelayAtk": stats.get("timeWaitDelayAttack", 0),
                            "gunsDistCoeff": stats.get("artilleryDistCoeff", 0),
                            "speedLimit": stats.get("speedLimit", 0),
                            "height": stats.get("height", 0),
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
                            "canUseOnEmpty": stats.get("canUseOnEmpty", False),
                            "activationDelay": stats.get("activationDelay", 0),
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

            for slot_info in prepared_consumable_data:
                t.writeln(f"  第 {slot_info['slot_num']} 槽位:")
                for idx, item in enumerate(slot_info["items"]):
                    t.writeln(f"    ({idx + 1}) {item['name']}")
                    num_str = "无限" if item['num'] == -1 else str(item['num'])
                    t.writeln(f"      数量: {num_str}")
                    t.writeln(f"      准备时间: {item['preparationTime']}s")
                    t.writeln(f"      作用时间: {item['workTime']}s")
                    t.writeln(f"      装填时间: {item['reloadTime']}s")
                    details = self._format_consumable_details(item)
                    for d in details:
                        t.writeln(f"      {d}")
                t.writeln()

        # ── 战斗指令 ──────────────────────────────────────
        rage = raw_data.get("A_Specials", {}).get("RageMode", {})
        if rage:
            rage_lines = self.parse_rage_mode_advanced(rage, raw_species)
            for line in rage_lines:
                t.writeln(line)
            t.writeln()

        # ── 模块数据 ──────────────────────────────────────
        combined_stats = {}
        drum_configs = {}
        has_pure_b = any(k.startswith("B_") for k in raw_data.keys() if isinstance(raw_data[k], dict))

        for mod_key, module_data in raw_data.items():
            if not isinstance(module_data, dict):
                continue
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
                for def_cat, def_pattern in self.DEFAULTS.items():
                    if def_pattern.search(mod_key):
                        current_cat = def_cat
                        target_letters = ["A"]
                        break

            if not target_letters:
                continue

            for letter in target_letters:
                if letter not in combined_stats:
                    combined_stats[letter] = {cat: [] for cat in self.PATTERNS.keys()}

            # 舰载机中队
            if current_cat in ["DiveBomber", "TorpedoBomber", "Fighter", "SkipBomber"]:
                planes = module_data.get("planes", [])
                if planes:
                    info = {"type": current_cat, "planes": planes}
                    for letter in target_letters:
                        if info not in combined_stats[letter][current_cat]:
                            combined_stats[letter][current_cat].append(info)
                continue

            # 空袭
            elif current_cat == "AirSupport":
                found_list = []
                def scan_as(d):
                    for k, v in d.items():
                        if isinstance(v, dict) and "Armament" in k:
                            found_list.append({
                                "ui_type": v.get("uiType", "damage"),
                                "plane_id": v.get("planeName", "Unknown"),
                                "charges": v.get("chargesNum", 0),
                                "reload": v.get("reloadTime", 0),
                                "work_time": v.get("workTime"),
                                "max_dist": v.get("maxDist", 0),
                                "min_dist": v.get("minDist", 0),
                                "is_fixed": v.get("useFixedTimeToAttackPoint", False)
                            })
                scan_as(module_data)
                for letter in target_letters:
                    if "AirSupport" not in combined_stats[letter]:
                        combined_stats[letter]["AirSupport"] = []
                    for item in found_list:
                        if item not in combined_stats[letter]["AirSupport"]:
                            combined_stats[letter]["AirSupport"].append(item)
                continue

            # 弹夹/弹鼓炮
            if current_cat == "Artillery":
                switch_conf = module_data.get("SwitchableModeArtilleryModule")
                drum_conf = module_data.get("DrumArtilleryModule")
                conf = switch_conf or drum_conf
                if conf:
                    mode_info = None
                    if switch_conf:
                        details = [
                            f"长装填: {switch_conf.get('fullReloadTime', 0)}s",
                            f"连发数量: {switch_conf.get('shotsCount', 0):.0f}",
                            f"连发间隔: {switch_conf.get('burstReloadTime', 0)}s"
                        ]
                        mode_info = {"header": "连发射击模式", "details": details, "modifiers": switch_conf.get("modifiers", {})}
                    elif drum_conf:
                        is_chargeable = drum_conf.get("isChargeable", False)
                        n_rounds = drum_conf.get('shotsCount', 2)
                        shot_delay = drum_conf.get('shotDelay', 0)
                        params = drum_conf.get("chargeTimeParams", [])
                        if is_chargeable:
                            header_name = "弹鼓炮"
                            details = [f"连发数量: {n_rounds:.0f}", f"连发间隔: {shot_delay}s"]
                            if len(params) >= 3:
                                mode_type = params[2]
                                if mode_type == 1:
                                    details.append(f"第 1 轮装填时间: {params[0]}s")
                                    details.append(f"第 2 ~ {n_rounds:.0f} 轮装填时间: {params[1]}s")
                                elif mode_type == 2:
                                    details.append(f"第 1 ~ {n_rounds - 1:.0f} 轮装填时间: {params[0]}s")
                                    details.append(f"第 {n_rounds:.0f} 轮(末轮)装填时间: {params[1]}s")
                        else:
                            is_switchable = drum_conf.get("isSwitchable", False)
                            switch_prefix = "可切换" if is_switchable else "强制"
                            header_name = f"{switch_prefix}连发射击-弹夹炮"
                            details = [
                                f"长装填时间: {drum_conf.get('fullReloadTime', 0)}s",
                                f"连发间隔: {shot_delay}s",
                                f"连发轮数: {n_rounds:.0f}"
                            ]
                        mode_info = {"header": header_name, "details": details, "modifiers": drum_conf.get("modifiers", {})}
                    if mode_info:
                        found_groups = re.findall(r'([A-Z]+)\d*_', mod_key)
                        for group in found_groups:
                            for letter in list(group):
                                drum_configs[letter] = mode_info

            # 通用武器提取
            if current_cat in ["Artillery", "ATBA", "AirDefense", "Torpedoes", "DepthChargeGuns"]:
                system_wide_info = {
                    "max_dist": module_data.get("maxDist", 0),
                    "sigma": module_data.get("sigmaCount", "N/A"),
                }
                for letter in target_letters:
                    if current_cat in ["Artillery", "ATBA"]:
                        combined_stats[letter][f"{current_cat}_System"] = system_wide_info

                for sk, sv in module_data.items():
                    if not isinstance(sv, dict):
                        continue
                    if any(kw in sk for kw in ["Aura", "Far", "Medium", "Near"]):
                        # 光环统一归到 AirDefense，不管它所在的模块类型
                        aura_cat = "AirDefense"
                        raw_id = sv.get("name", sk)
                        display_name = self.get_localized_weapon_name(raw_id)
                        is_bubble_layer = "_Bubbles" in sk
                        net_dmg = sv.get("areaDamage", 0)
                        net_period = sv.get("areaDamagePeriod", 0)
                        bubble_dmg = sv.get("bubbleDamage", 0)
                        bubble_explosion = sv.get("explosionCount", 0)
                        bubble_inner = sv.get("innerBubbleCount", 0)
                        bubble_outer = sv.get("outerBubbleCount", 0)
                        info = {
                            "id": sk, "name": display_name, "is_aura": True,
                            "is_bubble_layer": is_bubble_layer,
                            "area_damage": net_dmg, "area_period": net_period,
                            "bubble_damage": bubble_dmg,
                            "bubble_explosion": bubble_explosion,
                            "bubble_inner": bubble_inner,
                            "bubble_outer": bubble_outer,
                        }
                        for letter in target_letters:
                            # 确保 AirDefense 桶存在
                            if aura_cat not in combined_stats[letter]:
                                combined_stats[letter][aura_cat] = []
                            combined_stats[letter][aura_cat].append(info)
                        continue

                    # HP 模块 —— 按旧代码逻辑：Artillery / ATBA 也检测 AirDefense
                    check_hp_cats = [current_cat]
                    if current_cat in ["Artillery", "ATBA"]:
                        check_hp_cats.append("AirDefense")
                    for hp_cat in check_hp_cats:
                        hp_pattern = self.HP_PATTERNS.get(hp_cat)
                        if not hp_pattern or not hp_pattern.match(sk):
                            continue
                        raw_gun_id = sv.get("name", sk)
                        gun_name = self.get_localized_weapon_name(raw_gun_id)
                        hp_val = sv.get("maxHealth", 0)
                        caliber = sv.get("caliber", 0)
                        reload = sv.get("shotDelay", 0)
                        rot_speed = sv.get("rotationSpeed", 0)
                        barrels = sv.get("numBarrels", 0)
                        info = {
                            "id": sk, "gun_name": gun_name, "hp": hp_val,
                            "caliber": caliber, "reload": reload, "rot_speed": rot_speed,
                            "barrels": barrels, "is_hp": True,
                        }
                        if hp_cat in ["Artillery", "ATBA", "Torpedoes"]:
                            info.update({
                                "ammo_list": sv.get("ammoList", []),
                                "idealRadius": sv.get("idealRadius", 0),
                                "minRadius": sv.get("minRadius", 0),
                                "idealDistance": sv.get("idealDistance", 0),
                                "r_zero": sv.get("radiusOnZero", 0),
                                "r_delim": sv.get("radiusOnDelim", 0),
                                "r_max": sv.get("radiusOnMax", 0),
                                "delim": sv.get("delim", 0),
                            })
                        for letter in target_letters:
                            combined_stats[letter][hp_cat].append(info)
                        break

        # ── 渲染模块数据 ──────────────────────────────────
        for letter in sorted(combined_stats.keys()):
            t.writeln(f"【{letter} 武器模块】")
            stats = combined_stats[letter]

            # 主炮
            if stats.get("Artillery_System"):
                sys_info = stats["Artillery_System"]
                t.writeln(f"  主炮系统精度:")
                t.writeln(f"    最大射程: {sys_info['max_dist'] / 1000:.1f} km" if sys_info['max_dist'] else "")
                t.writeln(f"    Sigma: {sys_info['sigma']}")
            artillery_items = [x for x in stats.get("Artillery", []) if x.get("is_hp")]
            if artillery_items:
                # 按 (name, barrels, reload, dispersion params) 分组
                wp_counts = Counter()
                for i in artillery_items:
                    key = (i["gun_name"], i.get("barrels", 0), i.get("reload", 0),
                           i.get("idealRadius", 0), i.get("minRadius", 0), i.get("idealDistance", 0),
                           i.get("r_zero", 0), i.get("r_delim", 0), i.get("r_max", 0), i.get("delim", 0),
                           tuple(sorted(i.get("ammo_list", []))))
                    wp_counts[key] += 1
                t.writeln(f"  主炮:")
                for (name, barrels, reload, ir, mr, id_dist, rz, rd, rm, dl, ammo_tuple), count in wp_counts.items():
                    t.writeln(f"    - {name} x{count}")
                    t.writeln(f"      联装数: {barrels:.0f}")
                    t.writeln(f"      装填时间: {reload}s")
                    formula = self._dispersion_formula(ir, mr, id_dist)
                    if formula:
                        t.writeln(f"      横向散布公式: {formula}")
                    t.writeln(f"      纵向散步系数: {rz} ~ {rd} (R={dl * 100:.0f}%) ~ {rm}")
                    if ammo_tuple:
                        display_ammo = []
                        for a in ammo_tuple:
                            an = self.ammo_name_mapping.get(a.upper(), a)
                            display_ammo.append(f"{an} ({a})" if an != a else a)
                        t.writeln(f"      可用弹药:")
                        for aitem in display_ammo:
                            t.writeln(f"        - {aitem}")
            # 弹夹/弹鼓信息
            if letter in drum_configs:
                dm = drum_configs[letter]
                t.writeln(f"  特殊射击模式: {dm['header']}")
                for d in dm["details"]:
                    t.writeln(f"    - {d}")

            # 副炮
            atba_items = [x for x in stats.get("ATBA", []) if x.get("is_hp")]
            if atba_items:
                wp_counts = Counter()
                for i in atba_items:
                    key = (i["gun_name"], i.get("barrels", 0), i.get("reload", 0),
                           i.get("idealRadius", 0), i.get("minRadius", 0), i.get("idealDistance", 0),
                           i.get("r_zero", 0), i.get("r_delim", 0), i.get("r_max", 0), i.get("delim", 0),
                           tuple(sorted(i.get("ammo_list", []))))
                    wp_counts[key] += 1
                t.writeln(f"  副炮:")
                for (name, barrels, reload, ir, mr, id_dist, rz, rd, rm, dl, ammo_tuple), count in wp_counts.items():
                    t.writeln(f"    - {name} x{count}")
                    t.writeln(f"      联装数: {barrels:.0f}")
                    t.writeln(f"      装填时间: {reload}s")
                    formula = self._dispersion_formula(ir, mr, id_dist)
                    if formula:
                        t.writeln(f"      横向散布公式: {formula}")
                    t.writeln(f"      纵向散步系数: {rz} ~ {rd} (R={dl * 100:.0f}%) ~ {rm}")
                    if ammo_tuple:
                        display_ammo = []
                        for a in ammo_tuple:
                            an = self.ammo_name_mapping.get(a.upper(), a)
                            display_ammo.append(f"{an} ({a})" if an != a else a)
                        t.writeln(f"      可用弹药:")
                        for aitem in display_ammo:
                            t.writeln(f"        - {aitem}")
            if stats.get("ATBA_System"):
                sys_info = stats["ATBA_System"]
                t.writeln(f"    副炮射程: {sys_info['max_dist'] / 1000:.1f} km" if sys_info.get('max_dist') else "")

            # 鱼雷
            torp_items = [x for x in stats.get("Torpedoes", []) if x.get("is_hp")]
            if torp_items:
                wp_counts = Counter()
                for i in torp_items:
                    key = (i["gun_name"], i.get("barrels", 0), i.get("reload", 0),
                           tuple(sorted(i.get("ammo_list", []))))
                    wp_counts[key] += 1
                t.writeln(f"  鱼雷发射管:")
                for (name, barrels, reload, ammo_tuple), count in wp_counts.items():
                    t.writeln(f"    - {name} x{count}")
                    t.writeln(f"      联装数: {barrels:.0f}")
                    t.writeln(f"      装填时间: {reload}s")
                    if ammo_tuple:
                        display_ammo = []
                        for a in ammo_tuple:
                            an = self.ammo_name_mapping.get(a.upper(), a)
                            display_ammo.append(f"{an} ({a})" if an != a else a)
                        t.writeln(f"      可用弹药:")
                        for aitem in display_ammo:
                            t.writeln(f"        - {aitem}")
                    ammos = set()
                    for i in torp_items:
                        if i["gun_name"] == name:
                            for a in i.get("ammo_list", []):
                                ammo_name = self.ammo_name_mapping.get(a.upper(), a)
                                ammos.add(ammo_name)
                    if ammos:
                        t.writeln(f"      弹药: {' | '.join(sorted(ammos))}")

            # 防空
            aura_items = [x for x in stats.get("AirDefense", []) if x.get("is_aura")]
            hp_aa_items = [x for x in stats.get("AirDefense", []) if x.get("is_hp")]
            if aura_items:
                t.writeln(f"  防空光环:")
                for item in aura_items:
                    is_bubble = item.get("is_bubble_layer", False)
                    label = "黑云" if is_bubble else "持续伤害"
                    t.writeln(f"    - {item['name']} ({label})")
                    if is_bubble:
                        total = item['bubble_damage'] * 2 / item['area_period'] if item['area_period'] else 0
                        t.writeln(f"      黑云爆炸伤害: {total:.0f}")
                    else:
                        dps = item['area_damage'] / item['area_period'] if item['area_period'] else 0
                        t.writeln(f"      面板秒伤: {dps:.0f}")
            if hp_aa_items:
                # 过滤掉光环节点（Medium1, Near1 等不是真实防空炮）
                real_guns = [i for i in hp_aa_items
                             if not re.match(r'^(Medium|Near|Far)\d*_?', i.get("gun_name", ""))]
                if real_guns:
                    t.writeln(f"  防空炮:")
                    for name, count in Counter(i["gun_name"] for i in real_guns).items():
                        t.writeln(f"    - {name} x{count}")

            # 深水炸弹
            dc_items = [x for x in stats.get("DepthChargeGuns", []) if x.get("is_hp")]
            if dc_items:
                t.writeln(f"  深水炸弹:")
                for name, count in Counter(i["gun_name"] for i in dc_items).items():
                    t.writeln(f"    - {name} x{count}")

            # 舰载机
            for plane_cat in ["DiveBomber", "TorpedoBomber", "Fighter", "SkipBomber"]:
                plane_items = stats.get(plane_cat, [])
                for p in plane_items:
                    planes = p.get("planes", [])
                    for pl in planes:
                        if isinstance(pl, dict):
                            pname = pl.get("name", "Unknown")
                            display = self.get_localized_plane_name(pname)
                            t.writeln(f"  舰载机: {display}")
                            # 尝试显示弹药名
                            armament = pl.get("armamentName", "")
                            if armament:
                                ammo_name = self.ammo_name_mapping.get(armament.upper(), armament)
                                t.writeln(f"    弹药: {ammo_name}")

            # 空袭
            as_items = stats.get("AirSupport", [])
            if as_items:
                t.writeln(f"  空袭/支援:")
                for item in as_items:
                    plane_display = self.get_localized_plane_name(item.get('plane_id', ''))
                    t.writeln(f"    - 飞机: {plane_display}")
                    if item.get('charges'):
                        t.writeln(f"      次数: {item['charges']}")
                    if item.get('reload'):
                        t.writeln(f"      装填: {item['reload']}s")

            t.writeln()

        return t.result(title=real_name, subtitle=f"ID: {ship_index} | {NameMapping.SHIP_CLASS_MAP.get(raw_species, raw_species)}")
