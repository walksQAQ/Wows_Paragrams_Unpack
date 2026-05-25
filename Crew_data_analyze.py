import tkinter as tk
from NameMapping import Mapping as NameMapping


class CrewDataAnalyzer:
    META_KEYS = {
        "triggerType",
        "maxTriggerNum",
        "sortIndex",
        "damagePercentThreshold",
        "triggerAllowedShips",
        "triggerAllowedShipTypes",
        "triggerRibbonsNum",
        "triggerIsSubRibbons",
        "triggerJoinRibbons",
        "triggerRibbonsTypes",
    }

    def __init__(self, log_func=None):
        self.log_func = log_func

    def _log(self, message):
        if self.log_func:
            self.log_func(message)
        else:
            print(message)

    def _write_line(self, display_area, text, indent=0):
        display_area.insert(tk.END, f"{'  ' * indent}{text}\n")

    def _map_label(self, key):
        return NameMapping.MODIFIER_MAP.get(key, NameMapping.DETAIL_MAP.get(key, key))

    def _make_item(self, name, val, unit="", key=None, percent_talent=False, level_dependent=False):
        return {
            "name": name,
            "val": val,
            "unit": unit,
            "key": key or name,
            "percentTalent": percent_talent,
            "levelDependent": level_dependent,
        }

    def _format_value(self, key, value, percent_talent=False, level_dependent=False):
        # 数值显示格式统一写在这里；不同词条可以在这里分支单独改
        if key == "visibilityDistCoeff":
            if value < 1:
                return f"-{(1-value)*100:.2f}%"
            elif value > 1:
                return f"+{(value-1)*100:.2f}%"
            else:
                return None
        elif key == "planeVisibilityFactor":
            if value < 1:
                return f"-{(1-value)*100:.2f}%"
            elif value > 1:
                return f"+{(value-1)*100:.2f}%"
            else:
                return None
        elif key == "GMShotDelay":
            if value < 1:
                return f"-{(1-value)*100:.2f}%"
            elif value > 1:
                return f"+{(value-1)*100:.2f}%"
            else:
                return None
        elif key == "GSShotDelay":
            if value < 1:
                return f"-{(1-value)*100:.2f}%"
            elif value > 1:
                return f"+{(value-1)*100:.2f}%"
            else:
                return None
        elif key == "GTShotDelay":
            if value < 1:
                return f"-{(1-value)*100:.2f}%"
            elif value > 1:
                return f"+{(value-1)*100:.2f}%"
            else:
                return None
        elif key == "planeSpawnTime":
            if value < 1:
                return f"-{(1-value)*100:.2f}%"
            elif value > 1:
                return f"+{(value-1)*100:.2f}%"
            else:
                return None
        elif key == "planeSpeed":
            if value < 1:
                return f"-{(1-value)*100:.2f}%"
            elif value > 1:
                return f"+{(value-1)*100:.2f}%"
            else:
                return None
        elif key == "speedCoef":
            if value < 1:
                return f"-{(1-value)*100:.2f}%"
            elif value > 1:
                return f"+{(value-1)*100:.2f}%"
            else:
                return None
        elif key == "additionalConsumables":
            if value > 0:
                return f"+{value}"
            else:
                return None
        elif key == "planeAdditionalConsumables":
            if value > 0:
                return f"+{value}"
            else:
                return None
        elif key == "burnChanceBonus":
            if value > 0:
                return f"+{value*100:.2f}%"
            elif value < 0:
                return f"-{value*100:.2f}%"
            else:
                return None
        elif key == "burnChanceFactorBig":
            if value > 0:
                return f"+{value*100:.2f}%"
            elif value < 0:
                return f"-{value*100:.2f}%"
            else:
                return None
        elif key == "floodChanceFactorTorpedo":
            if value > 1:
                return f"+{(value-1)*100:.2f}%"
            elif value < 1:
                return f"-{(1-value)*100:.2f}%"
            else:
                return None
        elif key == "regenerationHPSpeed":
            if percent_talent == False:
                return f"+{value}"
            else:
                return f"+{value*100:.2f}%"
        elif key == "workTime":
            if level_dependent == False:
                return f"{value}s"
            else:
                return f"生效时间取决于舰船等级"
        elif key == "GMMaxDist":
            if value < 1:
                return f"-{(1-value)*100:.2f}%"
            elif value > 1:
                return f"+{(value-1)*100:.2f}%"
            else:
                return None
        elif key == "ConsumablesWorkTime":
            if value < 1:
                return f"-{(1-value)*100:.2f}%"
            elif value > 1:
                return f"+{(value-1)*100:.2f}%"
            else:
                return None
        elif key == "GMRotationSpeed":
            if value < 1:
                return f"-{(1-value)*100:.2f}%"
            elif value > 1:
                return f"+{(value-1)*100:.2f}%"
            else:
                return None
        elif key == "SGRudderTime":
            if value < 1:
                return f"-{(1-value)*100:.2f}%"
            elif value > 1:
                return f"+{(value-1)*100:.2f}%"
            else:
                return None
        elif key == "shootShift":
            if value < 1:
                return f"-{(1-value)*100:.2f}%"
            elif value > 1:
                return f"+{(value-1)*100:.2f}%"
            else:
                return None
        elif key == "ConsumableReloadTime":
            if value < 1:
                return f"-{(1-value)*100:.2f}%"
            elif value > 1:
                return f"+{(value-1)*100:.2f}%"
            else:
                return None
        elif key == "GMIdealRadius":
            if value < 1:
                return f"-{(1-value)*100:.2f}%"
            elif value > 1:
                return f"+{(value-1)*100:.2f}%"
            else:
                return None
        elif key == "planeSpreadMultiplier":
            if value < 1:
                return f"-{(1-value)*100:.2f}%"
            elif value > 1:
                return f"+{(value-1)*100:.2f}%"
            else:
                return None
        elif key == "GMAPDamageCoeff":
            if value < 1:
                return f"-{(1-value)*100:.2f}%"
            elif value > 1:
                return f"+{(value-1)*100:.2f}%"
            else:
                return None
        elif key == "AAAuraDamage":
            if value < 1:
                return f"-{(1-value)*100:.2f}%"
            elif value > 1:
                return f"+{(value-1)*100:.2f}%"
            else:
                return None
        elif key == "torpedoReloaderAdditionalConsumables":
            return f"+{value}"
        elif key == "torpedoReloaderReloadCoeff":
            if value < 1:
                return f"-{(1-value)*100:.2f}%"
            elif value > 1:
                return f"+{(value-1)*100:.2f}%"
            else:
                return None
        elif key == "torpedoSpeedMultiplier":
            if value < 1:
                return f"-{(1-value)*100:.2f}%"
            elif value > 1:
                return f"+{(value-1)*100:.2f}%"
            else:
                return None
        elif key in {"levelDependent", "percentTalent"}:
            return None
        return str(value)

    def _render_item(self, display_area, item, indent=0, bullet=True):
        name = item.get("name", "Unknown")
        value = item.get("val")
        unit = item.get("unit", "")
        percent_talent = item.get("percentTalent", False)
        level_dependent = item.get("levelDependent", False) # <-- 1. 获取当前层级的 level_dependent

        if isinstance(value, dict):
            prefix = "- " if bullet else ""
            self._write_line(display_area, f"{prefix}{name}:", indent)
            for child_key, child_value in value.items():
                if child_key in {"uniqueType"}:
                    continue

                child_name = NameMapping.SHIP_CLASS_MAP.get(child_key, self._map_label(child_key))
                parent_key = item.get("key", child_key)
                self._render_item(
                    display_area,
                    self._make_item(
                        child_name,
                        child_value,
                        key=parent_key,
                        percent_talent=percent_talent,
                        level_dependent=level_dependent  # <-- 2. 字典递归时向下传递
                    ),
                    indent + 1,
                )
            return

        if isinstance(value, list):
            prefix = "- " if bullet else ""
            self._write_line(display_area, f"{prefix}{name}:", indent)
            for child in value[:6]:
                if isinstance(child, dict):
                    self._render_item(
                        display_area,
                        self._make_item(
                            name,
                            child,
                            key=item.get("key", name),
                            percent_talent=percent_talent,
                            level_dependent=level_dependent # <-- 3. 列表递归字典时传递
                    ),
                        indent + 1,
                    )
                else:
                    # 4. 列表基础类型渲染时，传入 level_dependent
                    formatted_child = self._format_value(item.get('key', name), child, percent_talent, level_dependent)
                    if formatted_child is None or formatted_child == "":
                        continue
                    self._write_line(display_area, f"- {formatted_child}", indent + 1)
            return

        prefix = "- " if bullet else ""
        # 5. 普通键值对渲染时，必须传入 level_dependent 参数！
        formatted = self._format_value(item.get('key', name), value, percent_talent, level_dependent)
        if formatted is None or formatted == "":
            return
        self._write_line(display_area, f"{prefix}{name}: {formatted}{unit}", indent)

    def _render_items(self, display_area, items, indent=0, bullet=True):
        for item in items:
            self._render_item(display_area, item, indent, bullet)

    def _build_effect_items(self, effect_body):
        IGNORE_KEYS = {"levelDependent", "percentTalent", "uniqueType"}

        percent_talent = bool(effect_body.get("percentTalent", False))
        level_dependent = bool(effect_body.get("levelDependent", False))

        sub_items = []
        for key, value in effect_body.items():
            if key in IGNORE_KEYS:
                continue

            # 使用 _make_item 保留原始 key、本地化 name 以及对应数值
            sub_items.append(
                self._make_item(
                    name=self._map_label(key),
                    val=value,
                    key=key,
                    percent_talent=percent_talent,
                    level_dependent=level_dependent
                )
            )
        return sub_items

    def analyze(self, display_area, data):
        # 1. 先组装数据，再统一渲染，风格参考 ShipHullDataAnalyze
        header_items = [
            self._make_item("舰长名称", data.get("name", "Unknown_Crew")),
            self._make_item("舰长编号", data.get("index", "Unknown_Index")),
            self._make_item("所属国籍", data.get("typeinfo", {}).get("nation", "Unknown")),
        ]

        pers = data.get("CrewPersonality", {})
        personality_items = [
            self._make_item("是否为传奇舰长", "是" if pers.get("isUnique", False) else "否"),
            self._make_item("是否为动态舰长", "是" if pers.get("isAnimated", False) else "否"),
            self._make_item("是否为精英舰长", "是" if pers.get("isElite", False) else "否"),
            self._make_item("是否为特定历史人物", "是" if pers.get("isPerson", False) else "否"),
            self._make_item("是否可重训", "是" if pers.get("isRetrainable", False) else "否"),
        ]

        unique_skills = data.get("UniqueSkills", {})
        skill_sections = []
        for sk_key, sk_val in unique_skills.items():
            trigger_index = sk_val.get("sortIndex", 0)

            meta_items = []
            trigger_type = sk_val.get("triggerType")
            if trigger_type is not None:
                meta_items.append(self._make_item("激活方式", NameMapping.TRIGGER_TYPE_MAP.get(trigger_type, trigger_type)))

            max_trigger = sk_val.get("maxTriggerNum")
            if max_trigger is not None:
                meta_items.append(self._make_item("最大激活次数", max_trigger))

            if "triggerAchievement" in sk_val:
                # 先预留成就名映射：后续往 NameMapping.ACHIEVEMENT_MAP 填表即可
                ach_raw = sk_val.get("triggerAchievement")
                ach_name = NameMapping.ACHIEVEMENT_MAP.get(str(ach_raw), ach_raw)
                meta_items.append(self._make_item("激活所需成就", ach_name, key="triggerAchievement"))

            if "triggerDamageNum" in sk_val or "triggerDamageType" in sk_val:
                dmg_num = sk_val.get("triggerDamageNum")
                dmg_type_raw = sk_val.get("triggerDamageType")
                dmg_type_name = NameMapping.DAMAGE_TYPE_MAP.get(str(dmg_type_raw), dmg_type_raw)
                meta_items.append(self._make_item("激活所需受到伤害", f"{dmg_num} {dmg_type_name}", key="triggerDamageNum"))

            # 更细化的元信息处理：使用映射表本地化名称，并对勋带/阈值做额外映射/格式化
            # damagePercentThreshold -> 显示为百分比
            if "damagePercentThreshold" in sk_val:
                v = sk_val.get("damagePercentThreshold")
                try:
                    display_v = f"{float(v) * 100:.0f}%"
                except Exception:
                    display_v = v
                meta_items.append(self._make_item(self._map_label("对敌舰所造成的伤害"), display_v, key="damagePercentThreshold"))


            if "triggerRibbonsNum" in sk_val:
                meta_items.append(self._make_item(self._map_label("激活所需勋带数量"), sk_val.get("triggerRibbonsNum"), key="triggerRibbonsNum"))
            if "triggerIsSubRibbons" in sk_val:
                meta_items.append(self._make_item(self._map_label("激活所需勋带是否为子勋带"), sk_val.get("triggerIsSubRibbons"), key="triggerIsSubRibbons"))
            if "triggerJoinRibbons" in sk_val:
                meta_items.append(self._make_item(self._map_label("triggerJoinRibbons"), sk_val.get("triggerJoinRibbons"), key="triggerJoinRibbons"))

            # triggerRibbonsTypes -> 映射为勋带名称
            if "triggerRibbonsTypes" in sk_val:
                raw = sk_val.get("triggerRibbonsTypes")
                if isinstance(raw, (list, tuple)):
                    ribbons = raw
                else:
                    ribbons = [raw]
                ribbon_names = [NameMapping.RIBBON_MAP_CREW.get(str(r), str(r)) for r in ribbons]
                meta_items.append(self._make_item(self._map_label("激活所需勋带类型"), ribbon_names, key="triggerRibbonsTypes"))

            allowed = sk_val.get("triggerAllowedShips") or sk_val.get("triggerAllowedShipTypes")
            if allowed:
                meta_items.append(self._make_item("允许触发的舰种", [NameMapping.SHIP_CLASS_MAP.get(s, s) for s in allowed]))

            effect_items = []
            for effect_name, effect_body in sk_val.items():
                if effect_name in self.META_KEYS or not isinstance(effect_body, dict):
                    continue

                # 获取该子效果下的所有属性项（此时它们内部已经携带了正确的原始 key 和 percentTalent）
                sub_effects = self._build_effect_items(effect_body)
                if sub_effects:
                    effect_title = NameMapping.DETAIL_MAP.get(effect_name, effect_name)
                    # 将小标题和打包好的子项列表存入
                    effect_items.append({
                        "title": effect_title,
                        "sub_items": sub_effects
                    })

            skill_sections.append({
                "sort_index": trigger_index,
                "title": f"- 国家天赋{trigger_index}:",
                "items": meta_items,
                "effect_items": effect_items,
            })

        skill_sections.sort(key=lambda x: x.get("sort_index", 0))

        vanity = data.get("Vanity", {})
        vanity_items = [self._make_item("专属曳光弹", "有" if vanity.get("hasOwnTracer") else "无")]

        # 2. 统一渲染
        self._render_items(display_area, header_items, indent=0, bullet=False)
        self._write_line(display_area, "[舰长属性]", 0)
        self._render_items(display_area, personality_items, indent=1)

        if skill_sections:
            self._write_line(display_area, "[国家天赋]", 0)
            for skill in skill_sections:
                self._write_line(display_area, skill["title"], 0)
                self._render_items(display_area, skill["items"], indent=1)
                self._write_line(display_area, "- 加成效果:", 1)

                # --- 渲染改进后的分块数据 ---
                for eff in skill["effect_items"]:
                    # 1. 打印子效果代号/名称（如 UniqueRegen1）
                    self._write_line(display_area, f"- {eff['title']}:", 2)

                    # 2. 直接将打包好的子项送入原本的 _render_item 渲染，完全走正常的映射和格式化流程
                    for sub_item in eff["sub_items"]:
                        self._render_item(display_area, sub_item, indent=3, bullet=True)
                # -----------------------------
        else:
            self._write_line(display_area, "[国家天赋]", 0)
            self._write_line(display_area, "- 该舰长不是传奇舰长，无国家天赋。", 1)

        self._write_line(display_area, "[视觉效果]", 0)
        self._render_items(display_area, vanity_items, indent=1)
        display_area.insert(tk.END, "\n" + "=" * 45 + "\n\n")