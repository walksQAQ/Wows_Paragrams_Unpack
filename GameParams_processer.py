import struct
import sys
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
        # --- 统一路径逻辑：确保能定位到 EXE 旁边的 data 目录 ---
        if getattr(sys, "frozen", False):
            self.exe_dir = os.path.dirname(sys.executable)
        else:
            self.exe_dir = os.path.dirname(os.path.abspath(__file__))

    def load_and_decrypt(self, data_folder=None):
        """解密逻辑"""
        try:
            # 如果调用时没传路径，默认指向外部 data 目录
            if data_folder is None:
                data_folder = os.path.join(self.exe_dir, "data")

            target_names = ["GameParams_py2.data", "GameParams.data"]
            found_path = next(
                (os.path.join(data_folder, n) for n in target_names if os.path.exists(os.path.join(data_folder, n))),
                None)

            if not found_path:
                return False, f"未找到数据文件: {data_folder}"

            with open(found_path, 'rb') as f:
                gpd = f.read()
            gpd = struct.pack('B' * len(gpd), *gpd[::-1])
            gpd = zlib.decompress(gpd)
            self.data = pickle.loads(gpd, encoding='latin1')
            return True, "解析成功"
        except Exception as e:
            return False, str(e)

    def run_split_export(self, data_folder=None, output_dir=None):
        """
        导出逻辑：Lesta服去掉 0 层级，WG服去掉 root 层级
        """
        try:
            # 1. 确保数据已加载，传入 data_folder
            if self.data is None:
                success, msg = self.load_and_decrypt(data_folder)
                if not success: return False, msg

            # 2. 确定输出目录：默认输出到 EXE 同级目录的 data/split
            if output_dir is None:
                output_dir = os.path.join(self.exe_dir, "data", "split")

            if not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)

            # --- WG/Lesta 逻辑分流处理 ---
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
                        tpe.submit(self._write_single_file, k, v, None, output_dir)
                return True, "Wargaming服数据拆分完成"
            else:
                with ThreadPoolExecutor(max_workers=8) as tpe:
                    for index, elem in enumerate(self.data):
                        if not isinstance(elem, dict): continue
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