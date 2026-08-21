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
import threading
import zlib
from concurrent.futures import ThreadPoolExecutor

from app.signals import bus
from app.application import app as app_ctx
from utils.threading_utils import run_async
from utils.path_utils import get_data_dir, get_split_dir
from services.database_service import DatabaseManager, get_db, reset_db

from services import GameParams as _GameParamsModule
from services import wg_compat
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
        bus.task_progress.emit(80, "数据入库")
        if not version_code:
            version_code = db.get_latest_version_code() or ""
        svc.precompute_all(db, data_by_category=data_by_category, version_code=version_code)
        bus.task_progress.emit(100, "步骤 3/3: 数据入库完成")
    except Exception as e:
        bus.log_message.emit(f"⚠️ 预分析跳过: {e}")


def _save_ship_models(db, data_by_category: dict, version_code: str) -> None:
    """把可载入舰船列表（有 model 的 Ship）写入数据库 ship_models 表。

    3D 查看器的 list_ships 从该表读取，避免每次启动都扫描 data/split
    （keep_split_json=False 时该目录会被清理）。
    """
    try:
        ships = (data_by_category or {}).get("Ship") or {}
        items = []
        for key, v in ships.items():
            hull = v.get("A_Hull") or {}
            model = hull.get("model") or ""
            if not model:
                continue
            model_path = str(model)
            parts = [p for p in model_path.replace("\\", "/").split("/") if p]
            model_folder = parts[-2] if len(parts) >= 2 else ""
            nation = str(v.get("typeinfo", {}).get("nation", ""))
            items.append((key, model_folder, model_path, nation))
        n = db.save_ship_models(items, version_code)
        if n:
            bus.log_message.emit(f"📦 可载入舰船列表已记录: {n} 艘")
    except Exception as e:  # noqa: BLE001
        bus.log_message.emit(f"⚠️ 可载入舰船列表写入失败: {e}")


def run_process() -> "_AppTask":
    data_dir = get_data_dir()
    split_dir = get_split_dir()

    db: DatabaseManager | None = None
    # assets_data.db 后台缓存：完成事件 + 结果标志 + 是否启动（主流程需等它写完才标「全部完成」）
    assets_done = threading.Event()
    assets_ok = [False]
    assets_started = [False]

    def _finalize_import(db: DatabaseManager, db_batch: list, snapshots_batch: list,
                          data_by_category: dict, data_dir, version_code: str) -> None:
        db.insert_entities_batch(db_batch, version_code=version_code)
        # 同步写入实体快照（规范化 JSON），供跨版本字段级比对
        db.save_entity_snapshots(snapshots_batch, version_code=version_code)
        # 可载入舰船列表（3D 查看器用）：入库时一并记录，不依赖 data/split
        _save_ship_models(db, data_by_category, version_code)
        bus.task_progress.emit(45, "步骤 2/3: 写入数据库实体")
        ms = db.import_name_mappings(str(data_dir))
        bus.task_progress.emit(60, "步骤 2/3: 导入名称映射")
        bus.task_progress.emit(80, "步骤 3/3: 数据入库")
        bus.log_message.emit("🧠 步骤 3/3: 正在数据入库（内存模式）...")
        # 预提取 assets.bin 到**独立缓存库 assets_data.db**（与主库 game_data.db 无锁冲突）。
        # 在这里（分析开始前）后台启动，与下方 _run_analysis 写 game_data.db **同时进行**，
        # 缩短整体加载时长；3D 查看器只读该缓存库。
        assets_started[0] = True
        try:
            from utils.threading_utils import run_async

            def _assets_cache_job():
                try:
                    assets_ok[0] = _populate_assets_cache(
                        bin_folder=app_ctx.ctx.bin_folder,
                        game_version=app_ctx.ctx.game_version,
                        wows_type=app_ctx.ctx.wows_type)
                except Exception as e:  # noqa: BLE001
                    bus.log_message.emit(f"❌ assets_data.db 写入失败: {e}")
                    assets_ok[0] = False
                finally:
                    # populate 完成后清理 assets.bin 临时文件与索引缓存
                    # （data/assets.bin 提取产物 / data/assets_{bin_folder}.bin 版本缓存 / .uncode_cache）
                    _cleanup_assets_temp()
                    assets_done.set()

            run_async(_assets_cache_job)
        except Exception:  # noqa: BLE001
            assets_done.set()  # 启动失败兜底，避免主流程等待卡死
        # 主线程：分析并写 game_data.db（与 assets 后台缓存并行）
        _run_analysis(db, data_by_category, version_code=version_code)
        bus.log_message.emit(f"📦 步骤 3/3: 数据入库写入: {len(db_batch)} 条, 映射 {sum(ms.values())} 条 ({db.db_size_mb} MB)")
        bus.task_progress.emit(100, "步骤 3/3: 完成")

    # Gun 复用数据层已有的武器类型识别：不单独新增分析。
    # 数据层 DatabaseManager._entity_type("Gun")→"gun"、ENTITY_TYPES 含 "gun"、
    # guns_names.json 名称映射、entity_registry 注册与 entity_snapshots 快照均
    # 已覆盖 Gun（data/split/Gun/ 大量真实主炮/鱼雷/防空等实体）。这里保留
    # "Gun" 映射使其继续进入基础实体/快照管线；Gun 无独立分析桶，若日后需要
    # 结构化炮数据再另立 store_gun 功能。
    TYPE_CATEGORY_MAP = {
        "Ship": "Ship", "Gun": "Gun", "Projectile": "Projectile",
        "Aircraft": "Aircraft", "Ability": "Ability",
        "Modernization": "Modernization", "Crew": "Crew",
        "Other": "Other", "Exterior": "Exterior",
    }

    # 当前服务器生效的类型→类别映射：WG 若在 wg_compat 已填充则用 WG 版，否则回退 Lesta 默认
    # （WG 的 TypeInfo.type 集合/命名与 Lesta 可能有差异，差异由 wg_compat 预留，人工填充）
    _cat_map = wg_compat.get_type_category_map(app_ctx.ctx.wows_type) or TYPE_CATEGORY_MAP

    def _collect_one(k: str, v: dict, index):
        """线程安全收集单实体：返回独立结果，不共享可变状态（供并行收集）。

        返回 (cat, k, v, db_item, snap_item)：主线程合并到分类/批量列表。
        """
        t = v.get('typeinfo', {}).get('type', 'UnknownType')
        cat = _cat_map.get(t, None)
        db_item = (str(t), k, v)
        snap_item = (
            k,
            DatabaseManager._entity_type(str(t)),
            str(v.get('typeinfo', {}).get('nation', '')),
            json.dumps(v, sort_keys=True, ensure_ascii=False),
        )
        return cat, k, v, db_item, snap_item

    def _collect_all(ej, ti, db_batch, snapshots_batch, data_by_category, sd, do_write_json):
        """并行收集一批实体：CPU 密集的 json.dumps 与写 JSON 在线程池，主线程合并。

        ej 是只读 dict；每项在子线程独立序列化，返回独立结果，主线程 append
        到共享列表（无竞争）。比原主线程逐条 json.dumps 明显提速。
        """
        with ThreadPoolExecutor(max_workers=8) as tpe:
            write_futs = []
            collect_futs = []
            for k, v in ej.items():
                if do_write_json:
                    write_futs.append(tpe.submit(_write_one, k, v, ti, sd))
                collect_futs.append(tpe.submit(_collect_one, k, v, ti))
            for w in write_futs:
                try:
                    w.result()
                except Exception:  # noqa: BLE001
                    pass
            for f in collect_futs:
                cat, k, v, db_item, snap_item = f.result()
                if cat:
                    data_by_category.setdefault(cat, {})[k] = v
                db_batch.append(db_item)
                snapshots_batch.append(snap_item)

    def _process():
        nonlocal db
        if split_dir.exists():
            shutil.rmtree(str(split_dir))
        split_dir.mkdir(parents=True)

        for n in ["GameParams_py3.data", "GameParams_py2.data", "GameParams.data"]:
            p = data_dir / n
            if p.exists():
                found = str(p)
                break
        else:
            return False, f"未找到数据文件: {data_dir}"

        with open(found, 'rb') as f:
            gpd = f.read()
        gpd = gpd[::-1]
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
        snapshots_batch: list[tuple[str, str, str, str]] = []
        data_by_category: dict[str, dict[str, dict]] = {}
        sd = str(split_dir)
        do_write_json = app_ctx.config.keep_split_json
        msg = ""

        if source_dict:
            ej = json.loads(json.dumps(source_dict, cls=_GPEncode, ensure_ascii=False))
            _collect_all(ej, None, db_batch, snapshots_batch, data_by_category, sd, do_write_json)
            msg = "Wargaming 拆分完成"
        else:
            for idx, elem in enumerate(data):
                if not isinstance(elem, dict):
                    continue
                ti = None if idx == 0 else idx
                ej = json.loads(json.dumps(elem, cls=_GPEncode, ensure_ascii=False))
                _collect_all(ej, ti, db_batch, snapshots_batch, data_by_category, sd, do_write_json)
            msg = "Lesta 拆分完成"

        if db_batch:
            _finalize_import(db, db_batch, snapshots_batch, data_by_category, data_dir, version_code)
            # 等 assets_data.db 后台缓存跑完（成功或失败都等）
            if not assets_done.wait(timeout=900):
                bus.log_message.emit("⚠️ 3D 缓存（assets_data.db）等待超时")
            if not assets_ok[0]:
                # assets_data.db 写入失败/超时 → 主流程以报错方式终止（不标「全部完成」）
                return False, "3D 缓存（assets_data.db）写入失败，已终止加载流程"
        return True, msg

    def _ok(ret):
        # 由 threading_utils.run_async 投递到主线程执行：所有 UI 信号发射与
        # 数据库收尾（reset_db 关闭连接）都在主线程串行进行，避免后台线程
        # 关闭主线程正在使用的 sqlite 连接，引发"进度到最后时莫名崩溃"
        # （sqlite C 扩展段错误，无 traceback，打包后更易触发）。
        ok, msg = ret
        if ok:
            try:
                if not app_ctx.config.keep_split_json and split_dir.exists():
                    shutil.rmtree(str(split_dir))
                    bus.log_message.emit("🧹 split 临时文件已清理")
                for n in ["GameParams_py3.data", "GameParams_py2.data", "GameParams.data"]:
                    p = data_dir / n
                    if p.exists():
                        p.unlink()
                        bus.log_message.emit(f"🧹 已删除原始数据文件: {n}")
                # assets.bin 临时文件（data/assets.bin / assets_{bin_folder}.bin / .uncode_cache）
                # 由后台 _assets_cache_job 完成后统一清理（本流程可能仍在后台读取，避免竞争）
                # 只保留最新 2 个版本，滚动删除更旧的
                deleted = db.purge_old_versions(keep_count=2)
                if deleted:
                    bus.log_message.emit(f"📂 已清理旧版本数据 ({deleted} 条版本记录)")
                if assets_started[0]:
                    if assets_ok[0]:
                        bus.log_message.emit("✅ 3D 缓存（assets_data.db）已就绪")
                    else:
                        bus.log_message.emit("❌ 3D 缓存（assets_data.db）写入失败——3D 查看器可能缺少骨架/材质数据")
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
            # 失败终止同样收尾：关闭并重置数据库连接（避免 sqlite WAL 锁残留）
            try:
                if db is not None:
                    db.close()
            except Exception:
                pass
            reset_db()

    def _err(msg: str):
        # 由 run_async 在主线程执行，保证信号只在主线程发射
        bus.log_message.emit(f"❌ 解析失败: {msg}")
        bus.data_processed.emit(False)

    return run_async(_process, on_finished=_ok, on_error=_err)


def _populate_assets_cache(bin_folder: str, game_version: str, wows_type: str) -> bool:
    """把当前客户端 assets.bin 的 3D 查看器数据预提取到 assets_data.db。

    返回是否成功写入；过程中分阶段打日志（骨架/渲染集/材质）。
    """
    try:
        from services.assets_cache_service import AssetsCacheService
        from services.geometry_service import GeometryService
        gsvc = GeometryService.instance()
        path = gsvc.locate_assets_bin()
        if not path:
            bus.log_message.emit("⚠️ assets.bin 不可用，跳过 3D 数据缓存（3D 查看器将现场解析）")
            return False
        cache = AssetsCacheService(wows_type=wows_type)
        bus.log_message.emit("⏳ 步骤 3/3: 后台预提取 3D 数据（assets_data.db）...")
        counts = cache.populate(
            path, bin_folder=bin_folder or "",
            game_version=game_version or "",
            wows_type=wows_type or "",
            game_dir=app_ctx.ctx.game_path or None,
            progress_cb=lambda msg: bus.log_message.emit(f"⏳ 3D 缓存: {msg}"))
        bus.log_message.emit(
            f"📦 assets.bin 数据已缓存（骨架挂点 {counts['skeleton']} / "
            f"骨骼 {counts['skeleton_bones']} / 渲染集 {counts['render_sets']} / "
            f"材质 {counts['mfm_textures']} / 完整材质 {counts['material_full']}）")
        # 数据已全部入库，删除解包出来的临时 assets.bin 版本缓存（data/assets_*.bin），
        # 不再占用磁盘；3D 查看器后续直接从 assets_data.db 读取，无需该文件
        try:
            from utils.path_utils import get_data_dir
            removed = 0
            for p in get_data_dir().glob("assets_*.bin"):
                try:
                    p.unlink()
                    removed += 1
                except OSError:
                    pass
            if removed:
                bus.log_message.emit(f"🧹 已删除临时 assets.bin 解包缓存（{removed} 个）")
        except Exception:  # noqa: BLE001
            pass
        return True
    except Exception as e:  # noqa: BLE001
        bus.log_message.emit(f"❌ assets.bin 缓存写入失败: {e}")
        return False


def _cleanup_assets_temp() -> None:
    """清理 assets.bin 临时产物：data/assets.bin（提取产物）、data/assets_{bin_folder}.bin
    （版本缓存）、data/.uncode_cache（VFS 索引缓存）。在后台 assets 缓存入库完成后调用。"""
    try:
        from utils.path_utils import get_data_dir
        dd = get_data_dir()
        targets = [dd / "assets.bin"] + list(dd.glob("assets_*.bin")) + [dd / ".uncode_cache"]
        for p in targets:
            try:
                if p.is_dir():
                    shutil.rmtree(str(p), ignore_errors=True)
                elif p.exists():
                    p.unlink()
            except OSError:
                pass
    except Exception:  # noqa: BLE001
        pass
