"""
ConsumablePresenter —— 从 consumable_configs 表组装消耗品显示数据。

参照 _archive/analyzers/consumable_analyzer.py 的显示逻辑。
"""

from __future__ import annotations

import json

from presenters.base_presenter import BasePresenter, NM


class ConsumablePresenter(BasePresenter):
    """消耗品显示 Presenter"""

    @staticmethod
    def _merge_config_row(row) -> dict:
        """将 consumable_configs 行（列 + extra_json）合并为一个 cfg dict"""
        import json
        cfg = dict(row)
        COL2GAME = {
            "consumable_type": "consumableType",
            "num_consumables": "numConsumables",
            "work_time": "workTime",
            "preparation_time": "preparationTime",
            "reload_time": "reloadTime",
            "is_auto_consumable": "isAutoConsumable",
            "is_interceptor": "isInterceptor",
            "regen_hp_speed": "regenerationHPSpeed",
            "area_dmg_multiplier": "areaDamageMultiplier",
            "bubble_dmg_multiplier": "bubbleDamageMultiplier",
            "fighter_name": "fightersName",
            "fighter_num": "fightersNum",
            "available_buoyancy_states": "availableBuoyancyStates",
        }
        ej = cfg.pop('extra_json', None)
        extra = {}
        if ej:
            try:
                extra = json.loads(ej)
            except (json.JSONDecodeError, TypeError):
                pass
        result = {}
        for col, game_key in COL2GAME.items():
            if col in cfg and cfg[col] is not None:
                result[game_key] = cfg[col]
        result.update(extra)
        for _k in ('id', 'consumable_id', 'config_key'):
            result.pop(_k, None)
        return result

    def _load_cfg(self, cid: str, version_code: str = "") -> tuple[dict | None, str]:
        """从 consumable_configs 加载 Default 子配置，返回 (cfg_dict, type_str)"""
        conn = self.conn
        vc = self._ensure_version(version_code)
        cinfo = conn.execute(
            "SELECT * FROM consumable_basic_info WHERE version_code=? AND consumable_id=?",
            (vc, cid)).fetchone()
        if not cinfo:
            return None, ''

        row = conn.execute(
            "SELECT * FROM consumable_configs WHERE version_code=? AND consumable_id=? AND config_key='Default'",
            (vc, cid)).fetchone()
        if not row:
            row = conn.execute(
                "SELECT * FROM consumable_configs WHERE version_code=? AND consumable_id=? "
                "AND config_key NOT IN ('_top','custom','typeinfo') ORDER BY config_key LIMIT 1",
                (vc, cid)).fetchone()
        if not row:
            return {}, ''

        cfg = self._merge_config_row(row)
        ct = cfg.get('consumableType', '') or ''
        return cfg, ct

    def build(self, cid: str, version_code: str = "") -> dict | None:
        cfg, ct = self._load_cfg(cid, version_code)
        if cfg is None:
            return None

        display_name = cfg.pop('display_name', cid)
        items = [self.make_item(f"  名称: {display_name}", "", 0)]
        if ct:
            items.append(self.make_item(f"  类型: {ct}", "", len(items)))

        # 基础属性
        num_raw = cfg.get('num_consumables', '0')
        num_str = "无限" if str(num_raw) == '-1' else str(num_raw)
        items.append(self.make_item(f"  基础可用数量: {num_str}", "", len(items)))
        is_auto = cfg.get('is_auto_consumable', 0)
        if is_auto:
            items.append(self.make_item(f"  自动使用: 是", "", len(items)))
        prep = cfg.get('preparation_time', 0) or 0
        reload_t = cfg.get('reload_time', 0) or 0
        work = cfg.get('work_time', 0) or 0
        items.append(self.make_item(
            f"  准备时间: {prep}s / 冷却: {reload_t}s / 持续: {work}s", "", len(items)))

        # 按消耗品类型显示特殊属性
        items.append(self.make_item("  消耗品效果:", "", len(items)))
        if ct == "fighter":
            fn = self.resolve_name("plane", cfg.get('fightersName', '') or '未知')
            items.append(self.make_item(f"    战斗机: {fn}", "", len(items)))
            fn2 = cfg.get('fighterNum', 0)
            is_inter = cfg.get('isInterceptor', 0)
            items.append(self.make_item(f"    数量: {fn2} | 截击机: {'是' if is_inter else '否'}", "", len(items)))
            dog = cfg.get('dogFightTime', 0)
            fly = cfg.get('flyAwayTime', 0)
            if dog or fly:
                items.append(self.make_item(f"    狗斗: {dog}s | 离开: {fly}s", "", len(items)))
            rk = cfg.get('distanceToKill', 0)
            if rk:
                items.append(self.make_item(f"    巡逻半径: {rk/10:.1f}km", "", len(items)))
        elif ct == "scout":
            dc = (float(cfg.get('artilleryDistCoeff', 0) or 1) - 1)
            items.append(self.make_item(f"    主炮射程: {dc*100:+.2f}%", "", len(items)))
        elif ct == "smokeGenerator":
            r = float(cfg.get('radius', 0) or 0)
            h = float(cfg.get('height', 0) or 0)
            items.append(self.make_item(f"    烟雾半径: {r*3:.0f}m | 高度: {h}m", "", len(items)))
            sp = cfg.get('speedLimit', 0)
            lt = cfg.get('lifeTime', 0)
            if sp or lt:
                items.append(self.make_item(f"    速度限制: {sp}kts | 扩散: {lt}s", "", len(items)))
        elif ct == "speedBoosters":
            bc = (float(cfg.get('boostCoeff', 0) or 1) - 1)
            items.append(self.make_item(f"    最高航速: {bc*100:+.0f}%", "", len(items)))
            fe = (float(cfg.get('forwardEngineForsag', 0) or 1) - 1)
            be = (float(cfg.get('backwardEngineForsag', 0) or 1) - 1)
            items.append(self.make_item(f"    推力: 前进{fe*100:+.0f}% / 后退{be*100:+.0f}%", "", len(items)))
        elif ct == "sonar":
            ds = float(cfg.get('distShip', 0) or 0) * 0.03
            dt = float(cfg.get('distTorpedo', 0) or 0) * 0.03
            items.append(self.make_item(f"    舰船探测: {ds:.2f} km", "", len(items)))
            items.append(self.make_item(f"    鱼雷探测: {dt:.2f} km", "", len(items)))
            dm = float(cfg.get('distMine', 0) or 0) * 0.03
            if dm:
                items.append(self.make_item(f"    水雷探测: {dm:.2f} km", "", len(items)))
        elif ct == "torpedoReloader":
            trt = cfg.get('torpedoReloadTime', 0)
            if trt:
                items.append(self.make_item(f"    鱼雷装填时间: {trt}s", "", len(items)))
        elif ct == "rls":
            ds = float(cfg.get('distShip', 0) or 0) * 0.03
            items.append(self.make_item(f"    舰船探测: {ds:.2f} km", "", len(items)))
            aff = cfg.get('affectedClasses', [])
            if aff:
                cls_str = ', '.join(NM.SHIP_CLASS_MAP.get(c, c) for c in aff)
                items.append(self.make_item(f"    限制探测舰种: {cls_str}", "", len(items)))
        elif ct == "artilleryBoosters":
            bc = (float(cfg.get('boostCoeff', 0) or 1) - 1)
            items.append(self.make_item(f"    主炮装填时间: {bc*100:+.0f}%", "", len(items)))
        elif ct == "depthCharges":
            r = float(cfg.get('radius', 0) or 0) * 0.003
            items.append(self.make_item(f"    半径: {r:.2f}km", "", len(items)))
        elif ct == "hydrophone":
            zt = cfg.get('zoneLifeTime', 0)
            hu = cfg.get('hydrophoneUpdateFrequency', 0)
            if zt or hu:
                items.append(self.make_item(f"    虚影存留: {zt}s | 刷新: {hu}s", "", len(items)))
            wr = float(cfg.get('hydrophoneWaveRadius', 0) or 0) * 0.001
            if wr:
                items.append(self.make_item(f"    视野距离: {wr:.2f}km", "", len(items)))
        elif ct == "fastRudders":
            brt = (float(cfg.get('buoyancyRudderTimeCoeff', 0) or 1) - 1)
            bsc = (float(cfg.get('maxBuoyancySpeedCoeff', 0) or 1) - 1)
            items.append(self.make_item(f"    水平舵换挡: {brt*100:+.0f}%", "", len(items)))
            items.append(self.make_item(f"    上浮/下潜速度: {bsc*100:+.0f}%", "", len(items)))
        elif ct == "subsEnergyFreeze":
            items.append(self.make_item(f"    启用后下潜能力将停止消耗", "", len(items)))
            items.append(self.make_item(f"    可在电池耗尽时启用: {'是' if cfg.get('canUseOnEmpty') else '否'}", "", len(items)))
        elif ct == "submarineLocator":
            ds = float(cfg.get('distShip', 0) or 0) * 0.03
            items.append(self.make_item(f"    舰船探测: {ds:.2f} km", "", len(items)))
        elif ct == "planeSmokeGenerator":
            ad = cfg.get('activationDelay', 0)
            if ad:
                items.append(self.make_item(f"    生效延迟: {ad}s", "", len(items)))
            r = float(cfg.get('radius', 0) or 0) * 3
            items.append(self.make_item(f"    烟雾半径: {r:.0f}m", "", len(items)))
            h = float(cfg.get('height', 0) or 0)
            if h:
                items.append(self.make_item(f"    高度: {h}m", "", len(items)))
            sp = cfg.get('speedLimit', 0)
            if sp:
                items.append(self.make_item(f"    速度限制: {sp}kts", "", len(items)))
            lt = cfg.get('lifeTime', 0)
            if lt:
                items.append(self.make_item(f"    扩散时间: {lt}s", "", len(items)))
        elif ct == "supportBuoy":
            items.append(self.make_item(f"    区域: {cfg.get('battleDropVisualName', '未知')}", "", len(items)))
            items.append(self.make_item(f"    布置时间: {cfg.get('battleDropActivationTime', 0)}s", "", len(items)))
            items.append(self.make_item(f"    持续时间: {cfg.get('zoneLifetime', 0)}s", "", len(items)))
            items.append(self.make_item(f"    区域半径: {float(cfg.get('buffZoneRadius', 0) or 0) / 1000:.2f}km", "", len(items)))
            items.append(self.make_item(f"    效果持续时间: {cfg.get('buffDuration', 0)}s", "", len(items)))
        elif ct == "vampireDamage":
            coeff = float(cfg.get('damageGMHealCoeff', 0) or 0) * 100
            items.append(self.make_item(f"    伤害转化系数: {coeff:.2f}%", "", len(items)))
        elif ct == "massHeal":
            hp = float(cfg.get('ownHealPart', 0) or 0) * 100
            radius = float(cfg.get('workRadius', 0) or 0) * 3 / 100
            items.append(self.make_item(f"    自身每秒回复: {hp:.1f}%", "", len(items)))
            items.append(self.make_item(f"    友军增益: {cfg.get('allyBuffName', '')} Lv.{cfg.get('allyBuffLevel', 1)}", "", len(items)))
            items.append(self.make_item(f"    作用半径: {radius:.2f}km", "", len(items)))
        elif ct == "regenerateHealth":
            items.append(self.make_item("    恢复飞机中队部分生命值", "", len(items)))
        else:
            # 未知类型：尝试显示列 + extra_json 中非空值
            remaining = {k: v for k, v in cfg.items()
                         if v is not None and v != 0 and v != '' and k not in (
                             'num_consumables', 'preparation_time', 'work_time', 'reload_time',
                             'is_auto_consumable', 'display_name')}
            if remaining:
                items.append(self.make_item(f"    其他参数: {json.dumps(remaining, ensure_ascii=False)}", "", len(items)))

        return {
            "title": display_name,
            "subtitle": f"ID: {cid}",
            "sections": [self.make_section("详情", items)],
        }
