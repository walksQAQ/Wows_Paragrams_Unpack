import json
import os
import tkinter as tk


class CrewDataAnalyzer:
    def __init__(self, log_func=None):
        self.log_func = log_func

    def _log(self, message):
        if self.log_func:
            self.log_func(message)
        else:
            print(message)

    def analyze(self, display_area, data):
        # 1. 基础信息显示
        raw_full_name = data.get("name", "Unknown_Crew")
        display_area.insert(tk.END, f"舰长名称: {raw_full_name}\n")
        display_area.insert(tk.END, f"所属国籍: {data.get('typeinfo', {}).get('nation', 'Unknown')}\n")
        display_area.insert(tk.END, "-" * 30 + "\n")

        # [新增] 2. 舰长核心属性 (CrewPersonality)
        pers = data.get("CrewPersonality", {})
        display_area.insert(tk.END, "[舰长核心属性]\n")
        attr_list = [
            ("isUnique", "是否为传奇舰长舰长"),
            ("isAnimated", "是否为动态舰长"),
            ("isElite", "是否为精英舰长"),
            ("isPerson", "是否为特定历史人物"),
            ("isRetrainable", "是否可重训")
        ]
        for key, label in attr_list:
            status = "是" if pers.get(key, False) else "否"
            display_area.insert(tk.END, f"  - {label}: {status}\n")
        display_area.insert(tk.END, "\n") # 增加换行保持布局整洁

        # 3. 特殊技能解析
        unique_skills = data.get("UniqueSkills", {})
        if unique_skills:
            display_area.insert(tk.END, "[特殊技能触发机制]\n")
            for key, val in unique_skills.items():
                trigger = val.get("triggerAchievement", "未知成就")
                display_area.insert(tk.END, f"  - 触发条件: {trigger}\n")
                for effect_key, effect_val in val.items():
                    if isinstance(effect_val, dict):
                        for sub_k, sub_v in effect_val.items():
                            if "Boost" in effect_key or "Factor" in sub_k:
                                display_area.insert(tk.END, f"    > {sub_k}: {sub_v}\n")
        else:
            display_area.insert(tk.END, "[特殊技能]\n  - 该舰长无特殊天赋 (普通舰长)\n")

        # 4. 视觉效果部分
        vanity = data.get("Vanity", {})
        display_area.insert(tk.END, "\n[视觉效果]\n")
        tracer_status = "有" if vanity.get("hasOwnTracer") else "无"
        display_area.insert(tk.END, f"  - 专属曳光弹: {tracer_status}\n")

        display_area.insert(tk.END, "\n" + "=" * 45 + "\n\n")