"""
数据解析服务 —— 解密并拆分 GameParams.data。

内联了旧的 GameParams_processer.py。
"""

from __future__ import annotations

import json
import os
import pickle
import shutil
import struct
import sys
import zlib
from concurrent.futures import ThreadPoolExecutor

from app.signals import bus
from app.application import app as app_ctx
from utils.threading_utils import run_async
from utils.path_utils import get_data_dir, get_split_dir
from services.database_service import DatabaseManager, get_db, reset_db

# 将 services.GameParams 注册为 GameParams 模块，供 pickle.loads 反序列化时查找
from services import GameParams as _GameParamsModule
sys.modules['GameParams'] = _GameParamsModule


class _GPEncode(json.JSONEncoder):
    def default(self, o):
        try:
            for e in ['Cameras', 'DockCamera', 'damageDistribution', 'salvoParams']:
                if hasattr(o, '__dict__'):
                    o.__dict__.pop(e, None)
            return o.__dict__
        except AttributeError:
            return {}


def _write_one(key, value, index, out_dir):
    try:
        t = value.get('typeinfo', {}).get('type', 'UnknownType')
        d = os.path.join(out_dir, str(t)) if index is None else os.path.join(out_dir, str(index), str(t))
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{key}.json"), 'w', encoding='latin1') as f:
            json.dump(value, f, sort_keys=True, indent=4, separators=(',', ': '))
    except Exception:
        pass


def _run_analysis(db) -> None:
    """对数据库中所有实体运行分析器并写入结构化表"""
    try:
        from utils.path_utils import get_data_dir, get_split_dir
        data_dir = get_data_dir()
        split_dir = get_split_dir()

        # 检查 split 目录是否存在（keep_split_json=False 时会被删除）
        if not split_dir.exists():
            bus.log_message.emit("⏳ 跳过预分析：split 目录已被清理，数据已在首次入库时完成分析")
            return

        # 检查数据库是否已有名称映射（JSON 文件可能在导入后被清理）
        has_mappings = False
        try:
            row = db._conn.execute(
                "SELECT COUNT(*) FROM name_mappings").fetchone()
            has_mappings = row and row[0] > 0
        except Exception:
            pass
        if not has_mappings:
            bus.log_message.emit("⏳ 名称映射未入库，将使用原始 ID 作为显示名（稍后加载文本后自动更新）")

        from services.analysis_service import AnalysisService
        svc = AnalysisService()
        svc.initialize()
        if not svc.is_ready:
            return
        bus.task_progress.emit(80, "预分析数据")
        svc.precompute_all(db)
        bus.task_progress.emit(100, "预分析完成")
    except Exception as e:
        bus.log_message.emit(f"⚠️ 预分析跳过: {e}")


def run_process() -> None:
    data_dir = get_data_dir()
    split_dir = get_split_dir()

    db: DatabaseManager | None = None  # 在 run_process 作用域声明，_ok 能访问

    def _process():
        nonlocal db
        # 始终重建 split 目录用于分析，完成后根据 keep_split_json 决定是否保留
        if split_dir.exists():
            shutil.rmtree(str(split_dir))
        split_dir.mkdir(parents=True)

        for n in ["GameParams_py2.data", "GameParams.data"]:
            p = data_dir / n
            if p.exists():
                found = str(p)
                break
        else:
            return False, f"未找到数据文件: {data_dir}"

        with open(found, 'rb') as f:
            gpd = f.read()
        gpd = struct.pack('B' * len(gpd), *gpd[::-1])
        gpd = zlib.decompress(gpd)
        data = pickle.loads(gpd, encoding='latin1')

        source_dict = None
        if isinstance(data, (list, tuple)):
            for elem in data:
                if isinstance(elem, dict) and '' in elem and isinstance(elem[''], dict):
                    source_dict = elem['']
                    break
        elif isinstance(data, dict) and '' in data and isinstance(data[''], dict):
            source_dict = data['']

        # 统一使用 game_data.db，通过 load_seq 追踪版本
        db_path = DatabaseManager._versioned_path(data_dir, "", "")
        db = DatabaseManager(db_path)
        db.initialize()
        # 清理残留的分版本文件
        DatabaseManager.prune_old_files(data_dir)
        # 开始新的加载批次
        load_seq = db.begin_load(
            game_version=app_ctx.ctx.game_version,
            wows_type=app_ctx.ctx.wows_type,
            bin_folder=app_ctx.ctx.bin_folder)
        db_batch: list[tuple[str, str, dict]] = []

        def _write_one_db(k, v, index):
            t = v.get('typeinfo', {}).get('type', 'UnknownType')
            db_batch.append((str(t), k, v))

        sd = str(split_dir)
        if source_dict:
            ej = json.loads(json.dumps(source_dict, cls=_GPEncode, ensure_ascii=False))
            with ThreadPoolExecutor(max_workers=8) as tpe:
                for k, v in ej.items():
                    tpe.submit(_write_one, k, v, None, sd)
                    _write_one_db(k, v, None)
            if db_batch:
                db.insert_entities_batch(db_batch, load_seq=load_seq)
                bus.task_progress.emit(45, "写入数据库实体")
                ms = db.import_name_mappings(str(data_dir))
                bus.task_progress.emit(60, "导入名称映射")
                db.record_game_version(app_ctx.ctx.game_version, app_ctx.ctx.wows_type,
                                        app_ctx.ctx.bin_folder, entity_count=len(db_batch))
                bus.task_progress.emit(80, "预分析数据")
                bus.log_message.emit("🧠 正在预分析数据...")
                _run_analysis(db)
                bus.log_message.emit(f"📦 数据库写入: {len(db_batch)} 条, 映射 {sum(ms.values())} 条 ({db.db_size_mb} MB)")
                bus.task_progress.emit(100, "完成")
            return True, "Wargaming 拆分完成"
        else:
            with ThreadPoolExecutor(max_workers=8) as tpe:
                for idx, elem in enumerate(data):
                    if not isinstance(elem, dict):
                        continue
                    ti = None if idx == 0 else idx
                    ej = json.loads(json.dumps(elem, cls=_GPEncode, ensure_ascii=False))
                    for k, v in ej.items():
                        tpe.submit(_write_one, k, v, ti, sd)
                        _write_one_db(k, v, ti)
            if db_batch:
                db.insert_entities_batch(db_batch, load_seq=load_seq)
                bus.task_progress.emit(45, "写入数据库实体")
                ms = db.import_name_mappings(str(data_dir))
                bus.task_progress.emit(60, "导入名称映射")
                db.record_game_version(app_ctx.ctx.game_version, app_ctx.ctx.wows_type,
                                        app_ctx.ctx.bin_folder, entity_count=len(db_batch))
                bus.task_progress.emit(80, "预分析数据")
                bus.log_message.emit("🧠 正在预分析数据...")
                _run_analysis(db)
                bus.log_message.emit(f"📦 数据库写入: {len(db_batch)} 条, 映射 {sum(ms.values())} 条 ({db.db_size_mb} MB)")
                bus.task_progress.emit(100, "完成")
            return True, "Lesta 拆分完成"

    def _ok(ret):
        ok, msg = ret
        if ok:
            try:
                # 分析完成后，根据配置清理 split 目录
                if not app_ctx.config.keep_split_json and split_dir.exists():
                    shutil.rmtree(str(split_dir))
                    bus.log_message.emit("🧹 split 临时文件已清理")
                # 删除原始解包的 GameParams 数据文件
                for n in ["GameParams_py2.data", "GameParams.data"]:
                    p = data_dir / n
                    if p.exists():
                        p.unlink()
                        bus.log_message.emit(f"🧹 已删除原始数据文件: {n}")
                # 只保留最新 2 次加载的数据，删除更旧的批次
                deleted = db.purge_old_loads(keep_count=2)
                if deleted:
                    bus.log_message.emit(f"📂 已清理上上次的旧版本数据 ({deleted} 实体)")
                bus.log_message.emit(f"✅ 数据解析完成: {msg}")
                bus.task_progress.emit(100, "全部完成")
                app_ctx.set_game_data_state(True)
                bus.data_processed.emit(True)
                bus.folder_selected.emit("__REFRESH__")
            finally:
                # 关闭后台线程的数据库连接
                if db is not None:
                    try:
                        db.close()
                    except Exception:
                        pass
                from services.database_service import reset_db
                reset_db()
        else:
            bus.log_message.emit(f"❌ {msg}")
            bus.data_processed.emit(False)

    def _err(msg: str):
        bus.log_message.emit(f"❌ 解析失败: {msg}")
        bus.data_processed.emit(False)

    run_async(_process, on_finished=_ok, on_error=_err)
