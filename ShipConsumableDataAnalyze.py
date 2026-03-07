import os
import json


class ShipConsumableDataAnalyze:
    def __init__(self, base_dir):
        self.ability_dir = os.path.join(base_dir, "data", "split", "Ability")
        self.registry = {}
        self._load_all_ability_files()

    def _load_all_ability_files(self):
        if not os.path.exists(self.ability_dir):
            return

        for filename in os.listdir(self.ability_dir):
            if filename.endswith(".json"):
                key = filename.replace(".json", "")
                try:
                    with open(os.path.join(self.ability_dir, filename), 'r', encoding='utf-8') as f:
                        self.registry[key] = json.load(f)
                except Exception as e:
                    print(f"解析能力文件 {filename} 失败: {e}")

    def analyzeConsumableData(self, consumable_file_key, config_key):
        configs = self.registry.get(consumable_file_key, {})
        # 返回指定配置或 Default
        return configs.get(config_key) or configs.get("Default", {})

    def _parse_config(self, item_name, config):
        """
        全量提取模式：
        将原始 config 中的所有属性完整继承，并注入自定义的显示字段。
        """
        # 1. 拷贝所有原始数据，确保“全量继承”
        data_entry = config.copy()

        # 2. 注入 UI 所需的核心字段
        data_entry.update({
            "name": config.get("titleIDs") or item_name,
            "display_num": "无限" if config.get("numConsumables") == -1 else config.get("numConsumables", "未知"),
            "display_reload": f"{config.get('reloadTime', 0)}s",
        })

        return data_entry