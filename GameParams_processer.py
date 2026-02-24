import struct
import zlib
import pickle
import json
import os
from concurrent.futures import ThreadPoolExecutor


class GPEncode(json.JSONEncoder):
    """保持 WG 服处理脚本的过滤逻辑"""

    def default(self, o):
        try:
            for e in ['Cameras', 'DockCamera', 'damageDistribution', 'salvoParams']:
                if hasattr(o, '__dict__'):
                    o.__dict__.pop(e, None)
            return o.__dict__
        except AttributeError:
            return {}


class GameParamsProcessor:
    def __init__(self):
        self.data = None

    def load_and_decrypt(self, data_folder):
        """解密逻辑"""
        try:
            target_names = ["GameParams_py2.data", "GameParams.data"]
            found_path = next(
                (os.path.join(data_folder, n) for n in target_names if os.path.exists(os.path.join(data_folder, n))),
                None)

            if not found_path:
                return False, "未找到数据文件"

            with open(found_path, 'rb') as f:
                gpd = f.read()
            gpd = struct.pack('B' * len(gpd), *gpd[::-1])
            gpd = zlib.decompress(gpd)
            self.data = pickle.loads(gpd, encoding='latin1')
            return True, "解析成功"
        except Exception as e:
            return False, str(e)

    def run_split_export(self, data_folder, output_dir):
        """
        导出逻辑：Lesta服去掉 0 层级，WG服去掉 root 层级
        """
        try:
            if self.data is None:
                self.load_and_decrypt(data_folder)

            if not os.path.exists(output_dir):
                os.makedirs(output_dir)

            # --- Wargaming 服数据处理 (Root 模式) ---
            source_dict = None
            if isinstance(self.data, (list, tuple)):
                for elem in self.data:
                    if isinstance(elem, dict) and '' in elem and isinstance(elem[''], dict):
                        source_dict = elem['']
                        break
            elif isinstance(self.data, dict) and '' in self.data and isinstance(self.data[''], dict):
                source_dict = self.data['']

            if source_dict:
                elem_json = json.loads(json.dumps(source_dict, cls=GPEncode, ensure_ascii=False))
                with ThreadPoolExecutor(max_workers=8) as tpe:
                    for k, v in elem_json.items():
                        # WG服模式传入 None，去掉 root 目录
                        tpe.submit(self._write_single_file, k, v, None, output_dir)
                return True, "Wargaming服数据拆分完成"

            # --- Lesta 服数据处理 (列表模式) ---
            else:
                with ThreadPoolExecutor(max_workers=8) as tpe:
                    for index, elem in enumerate(self.data):
                        if not isinstance(elem, dict): continue

                        # --- 核心修改：如果是索引 0，则设为 None 以去掉目录层级 ---
                        target_index = None if index == 0 else index

                        elem_json = json.loads(json.dumps(elem, cls=GPEncode, ensure_ascii=False))
                        for k, v in elem_json.items():
                            tpe.submit(self._write_single_file, k, v, target_index, output_dir)
                return True, "Lesta服数据拆分完成"

        except Exception as e:
            return False, f"拆分失败: {e}"

    def _write_single_file(self, key, value, index, output_dir):
        """
        按照路径结构写入。如果 index 为 None，则路径为 output_dir/type/key.json
        """
        try:
            t = value.get('typeinfo', {}).get('type', 'UnknownType')

            # 判断路径结构
            if index is not None:
                # 针对 Lesta 服非 0 索引的情况：split/1/Ship/...
                target_dir = os.path.join(output_dir, str(index), str(t))
            else:
                # 针对 WG 服 或 Lesta 服索引 0 的情况：split/Ship/...
                target_dir = os.path.join(output_dir, str(t))

            if not os.path.exists(target_dir):
                os.makedirs(target_dir)

            file_path = os.path.join(target_dir, f"{key}.json")
            with open(file_path, 'w', encoding='latin1') as f:
                json.dump(value, f, sort_keys=True, indent=4, separators=(',', ': '))
        except:
            pass