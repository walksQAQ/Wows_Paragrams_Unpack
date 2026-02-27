import re
import json
import os
import sys


class POToolkit:
    def __init__(self, input_po_name="global_zh_sg.po", output_subdir="data"):
        self.base_path = self._get_base_path()
        self.input_po_path = os.path.join(self.base_path, input_po_name)
        self.output_dir = os.path.join(self.base_path, output_subdir)
        self.content = ""

    def _get_base_path(self):
        """获取程序可执行文件所在的真实目录 (兼容 PyInstaller)"""
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.abspath(__file__))

    def load_po_file(self):
        """加载文件内容，并统一特殊字符"""
        try:
            if not os.path.exists(self.input_po_path):
                return False, f"File not found: {self.input_po_path}"

            with open(self.input_po_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # --- 新增功能：统一间隔符 ---
            # 将所有不规范的 ˙ (U+02D9) 替换为标准中点 · (U+00B7)
            self.content = content.replace('˙', '·')
            # --------------------------

            return True, "Success"
        except Exception as e:
            return False, str(e)

    def _save_json(self, data, filename):
        """内部保存逻辑"""
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

        output_path = os.path.join(self.output_dir, filename)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        return output_path

    def extract_abilities(self):
        """提取消耗品名称"""
        pattern = re.compile(
            r'msgid "IDS_DOCK_CONSUME_TITLE_((?:P[XYC]\d{3}|[A-Z0-9]+)_[A-Z0-9_]+)"\s+msgstr "(.*?)"',
            re.MULTILINE
        )
        matches = pattern.findall(self.content)
        results = {core_id: msgstr for core_id, msgstr in matches
                   if msgstr.strip() and not msgstr.startswith("IDS_")}
        return self._save_json(results, "consumable_names.json"), len(results)

    def extract_rage_mode(self):
        """提取狂暴模式名称"""
        prefix = "IDS_DOCK_RAGE_MODE_TITLE_"
        pattern = re.compile(r'msgid\s+"({prefix}.*?)"\s+msgstr\s+"(.*?)"'.format(prefix=prefix), re.MULTILINE)
        matches = pattern.findall(self.content)
        results = {msgid: msgstr for msgid, msgstr in matches if msgstr.strip()}
        return self._save_json(results, "rage_mode_names.json"), len(results)

    def extract_ship_names(self):
        """提取舰船名称"""
        ship_mapping = {}
        id_pattern = re.compile(r'^msgid\s+"IDS_(P[A-Z]S([ABCDSX])\d+)"$')
        str_pattern = re.compile(r'^msgstr\s+"(.*)"$')

        lines = self.content.splitlines()
        current_id = None
        for line in lines:
            line = line.strip()
            id_match = id_pattern.match(line)
            if id_match:
                current_id = id_match.group(1)
                continue
            if current_id and line.startswith('msgstr "'):
                str_match = str_pattern.match(line)
                if str_match:
                    translation = str_match.group(1)
                    if translation and not translation.isdigit():
                        ship_mapping[current_id] = translation
                current_id = None
        return self._save_json(ship_mapping, "ship_names.json"), len(ship_mapping)

    def extract_gun_names(self):
        """
        提取火炮名称 (如 PAGS029_5in51_Mk_7, PAGM125_14in_45_Mk8)
        匹配规则：IDS_ 开头，接着是 PAG 开头的火炮 ID
        """
        pattern = re.compile(
            r'msgid "IDS_(P[A-Z]G[A-Z]+.*?)"\s+msgstr "(.*?)"',
            re.MULTILINE
        )
        matches = pattern.findall(self.content)
        # 过滤空翻译
        results = {core_id: msgstr for core_id, msgstr in matches
                   if msgstr.strip() and not msgstr.startswith("IDS_DOCK")}  # 避免抓到描述文字

        return self._save_json(results, "guns_names.json"), len(results)

    def extract_ammo_names(self):
        """
        提取弹药名称 (如 PZPT056_HENGSHUI, PRPA910_130MM_HE_SG_KREMLIN)
        匹配规则：IDS_P[字母]P 开头，包含指定类别字母(ABDLMRTW)，后接数字
        """
        # 1. 这里的正则适配 self.content 这种原始 PO 文本格式
        # 注意：增加了对文本中 msgid "IDS_..." 的包装匹配
        pattern = re.compile(
            r'msgid "IDS_(P[A-Z]P[ABDLMRTW]+\d+\S*?)"\s+msgstr "(.*?)"',
            re.MULTILINE
        )

        matches = pattern.findall(self.content)

        # 2. 转换并清洗数据
        ammo_map = {}
        for core_id, msgstr in matches:
            msgstr = msgstr.strip()
            # 过滤：空翻译、未完成翻译、或 IDS_DOCK 描述类文字
            if msgstr and not msgstr.startswith("IDS_"):
                # 统一转大写，确保匹配稳定性
                ammo_map[core_id.upper()] = msgstr

        return self._save_json(ammo_map, "ammo_names.json"), len(ammo_map)

    def extract_modernization_names(self):
        """
        提取升级品（插件）名称
        匹配类似: PCM001, PCM012, PCM912_T11_SS_SUpgrade_Mod_III_TEST 等
        """
        # 正则逻辑：
        # 1. 匹配以 IDS_TITLE_ 或 IDS_MODERNIZATION_ 开头的 msgid
        # 2. 核心 ID 必须包含 PCM (普通/传奇插件) 或 PUM (某些特殊插件)
        # 3. 排除一些常见的无关前缀，确保只抓取名称
        pattern = re.compile(
            r'msgid "IDS_(?:TITLE_|MODERNIZATION_)?(P[CU]M\d{3}[A-Z0-9_]*?)"\s+msgstr "(.*?)"',
            re.MULTILINE
        )

        matches = pattern.findall(self.content)

        mod_map = {}
        for core_id, msgstr in matches:
            msgstr = msgstr.strip()
            # 过滤掉空翻译和系统占位符
            if msgstr and not msgstr.startswith("IDS_"):
                # 键统一转大写，增强 ModernizationDataAnalyzer 的匹配兼容性
                mod_map[core_id.upper()] = msgstr

        return self._save_json(mod_map, "modernization_names.json"), len(mod_map)

    def extract_plane_name(self):
        # 修改点 1：正则增加第二个捕获组 (.*?) 来抓取 msgstr 里的内容
        # 修改点 2：增加 \s+msgstr " 来匹配中间的换行和固定字符
        pattern = re.compile(
            r'msgid "IDS_(P[A-Z]A[BDFMLSX][A-Z0-9_]*)"\s+msgstr "(.*?)"',
            re.MULTILINE
        )

        matches = pattern.findall(self.content)
        plane_map = {}

        # 现在 matches 的每一项都是 (ID, 翻译) 的元组，可以正常解包了
        for core_id, msgstr in matches:
            msgstr = msgstr.strip()
            # 过滤掉未翻译的条目
            if msgstr and not msgstr.startswith("IDS_"):
                plane_map[core_id.upper()] = msgstr

        return self._save_json(plane_map, "plane_names.json"), len(plane_map)

    def run_all(self):
        """
        供外部程序调用的主接口
        返回格式: (bool_是否全部成功, dict_统计信息或错误信息)
        """
        success, msg = self.load_po_file()
        if not success:
            return False, {"error": msg}

        stats = {}
        path1, count1 = self.extract_abilities()
        path2, count2 = self.extract_rage_mode()
        path3, count3 = self.extract_ship_names()
        path4, count4 = self.extract_gun_names()
        path5, count5 = self.extract_ammo_names()
        path6, count6 = self.extract_modernization_names()
        path7, count7 = self.extract_plane_name()

        stats["abilities"] = {"path": path1, "count": count1}
        stats["rage_mode"] = {"path": path2, "count": count2}
        stats["ship_names"] = {"path": path3, "count": count3}
        stats["weapons"] = {"path": path4, "count": count4}
        stats["ammos"] = {"path": path5, "count": count5}
        stats["modernizations"] = {"path": path6, "count": count6}
        stats["planes"] = {"path": path7, "count": count7}

        return True, stats