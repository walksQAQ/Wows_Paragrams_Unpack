"""
数据解析服务 —— 解密并拆分 GameParams.data（适配多版本架构）。
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


def _run_analysis(db, data_by_category: dict[str, dict[str, dict]] | None = None,
                  version_code: str = "") -> None:
    """对数据库中所有实体运行分析器并写入结构化表"""
    try:
        if not data_by_category:
            split_dir = get_split_dir()
            if not split_dir.exists():
                bus.log_message.emit("⏳ 跳过预分析：split 目录已被清理")
                return

        from services.analysis_service import AnalysisService
        svc = AnalysisService()
        svc.initialize()
        if not svc.is_ready:
            return
        bus.task_progress.emit(80, "预分析数据")
        if not version_code:
            version_code = db.get_latest_version_code() or ""
        svc.precompute_all(db, data_by_category=data_by_category, version_code=version_code)
        bus.task_progress.emit(100, "步骤 3/3: 预分析完成")
    except Exception as e:
        bus.log_message.emit(f"⚠️ 预分析跳过: {e}")


def run_process() -> None:
    data_dir = get_data_dir()
    split_dir = get_split_dir()

    db: DatabaseManager | None = None

    def _finalize_import(db: DatabaseManager, db_batch: list, data_by_category: dict,
                          data_dir, version_code: str) -> None:
        db.insert_entities_batch(db_batch, version_code=version_code)
        bus.task_progress.emit(45, "步骤 2/3: 写入数据库实体")
        ms = db.import_name_mappings(str(data_dir))
        bus.task_progress.emit(60, "步骤 2/3: 导入名称映射")
        bus.task_progress.emit(80, "步骤 3/3: 预分析数据")
        bus.log_message.emit("🧠 步骤 3/3: 正在预分析数据（内存模式）...")
        _run_analysis(db, data_by_category, version_code=version_code)
        bus.log_message.emit(f"📦 步骤 3/3: 数据库写入: {len(db_batch)} 条, 映射 {sum(ms.values())} 条 ({db.db_size_mb} MB)")
        bus.task_progress.emit(100, "步骤 3/3: 完成")

    TYPE_CATEGORY_MAP = {
        "Ship": "Ship", "Gun": "Gun", "Projectile": "Projectile",
        "Aircraft": "Aircraft", "Ability": "Ability",
        "Modernization": "Modernization", "Crew": "Crew",
    }

    def _collect_entity(k: str, v: dict, data_by_category: dict,
                         db_batch: list, index) -> None:
        t = v.get('typeinfo', {}).get('type', 'UnknownType')
        cat = TYPE_CATEGORY_MAP.get(t, None)
        if cat:
            data_by_category.setdefault(cat, {})[k] = v
        db_batch.append((str(t), k, v))

    def _process():
        nonlocal db
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

        # 使用服务器对应的数据库文件
        from utils.path_utils import get_data_dir
        db_path = str(get_data_dir() / DatabaseManager._db_name(app_ctx.ctx.wows_type))
        db = DatabaseManager(db_path=db_path)
        db.initialize()

        # 创建新版本记录
        version_code = db.begin_version(
            game_version=app_ctx.ctx.game_version,
            wows_type=app_ctx.ctx.wows_type,
            bin_folder=app_ctx.ctx.bin_folder)

        db_batch: list[tuple[str, str, dict]] = []
        data_by_category: dict[str, dict[str, dict]] = {}
        sd = str(split_dir)
        do_write_json = app_ctx.config.keep_split_json
        msg = ""

        if source_dict:
            ej = json.loads(json.dumps(source_dict, cls=_GPEncode, ensure_ascii=False))
            if do_write_json:
                with ThreadPoolExecutor(max_workers=8) as tpe:
                    for k, v in ej.items():
                        tpe.submit(_write_one, k, v, None, sd)
                        _collect_entity(k, v, data_by_category, db_batch, None)
            else:
                for k, v in ej.items():
                    _collect_entity(k, v, data_by_category, db_batch, None)
            msg = "Wargaming 拆分完成"
        else:
            for idx, elem in enumerate(data):
                if not isinstance(elem, dict):
                    continue
                ti = None if idx == 0 else idx
                ej = json.loads(json.dumps(elem, cls=_GPEncode, ensure_ascii=False))
                if do_write_json:
                    with ThreadPoolExecutor(max_workers=8) as tpe:
                        for k, v in ej.items():
                            tpe.submit(_write_one, k, v, ti, sd)
                            _collect_entity(k, v, data_by_category, db_batch, ti)
                else:
                    for k, v in ej.items():
                        _collect_entity(k, v, data_by_category, db_batch, ti)
            msg = "Lesta 拆分完成"

        if db_batch:
            _finalize_import(db, db_batch, data_by_category, data_dir, version_code)
        return True, msg

    def _ok(ret):
        ok, msg = ret
        if ok:
            try:
                if not app_ctx.config.keep_split_json and split_dir.exists():
                    shutil.rmtree(str(split_dir))
                    bus.log_message.emit("🧹 split 临时文件已清理")
                for n in ["GameParams_py2.data", "GameParams.data"]:
                    p = data_dir / n
                    if p.exists():
                        p.unlink()
                        bus.log_message.emit(f"🧹 已删除原始数据文件: {n}")
                # 只保留最新 2 个版本，滚动删除更旧的
                deleted = db.purge_old_versions(keep_count=2)
                if deleted:
                    bus.log_message.emit(f"📂 已清理旧版本数据 ({deleted} 条版本记录)")
                bus.log_message.emit(f"✅ 数据解析完成: {msg}")
                bus.task_progress.emit(100, "全部完成")
                app_ctx.set_game_data_state(True)
                bus.data_processed.emit(True)
                bus.folder_selected.emit("__REFRESH__")
            finally:
                if db is not None:
                    try:
                        db.close()
                    except Exception:
                        pass
                reset_db()
        else:
            bus.log_message.emit(f"❌ {msg}")
            bus.data_processed.emit(False)

    def _err(msg: str):
        bus.log_message.emit(f"❌ 解析失败: {msg}")
        bus.data_processed.emit(False)

    run_async(_process, on_finished=_ok, on_error=_err)
