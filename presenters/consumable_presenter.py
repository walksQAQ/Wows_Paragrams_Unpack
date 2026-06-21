"""
ConsumablePresenter —— 从 consumable_basic_info 表组装消耗品显示数据。

参照 _archive/analyzers/consumable_analyzer.py 的显示逻辑。
"""

from __future__ import annotations

import json

from presenters.base_presenter import BasePresenter, NM


class ConsumablePresenter(BasePresenter):
    """消耗品显示 Presenter"""

    def build(self, cid: str) -> dict | None:
        conn = self.conn
        c = conn.execute(
            "SELECT * FROM consumable_basic_info WHERE consumable_id=?",
            (cid,)).fetchone()
        if not c:
            return None

        items = [self.make_item(f"  名称: {c['display_name'] or cid}", "", 0)]
        ct = c['consumable_type'] or ''
        if ct:
            items.append(self.make_item(f"  类型: {ct}", "", len(items)))

        # 基础属性
        num_str = "无限" if c['num_consumables'] == '-1' else str(c['num_consumables'] or '?')
        items.append(self.make_item(f"  基础可用数量: {num_str}", "", len(items)))
        items.append(self.make_item(
            f"  自动使用: {'是' if c['is_auto_consumable'] else '否'}", "", len(items)))
        items.append(self.make_item(
            f"  准备时间: {c['preparation_time'] or 0}s"
            f" / 冷却: {c['reload_time'] or 0}s"
            f" / 持续: {c['work_time'] or 0}s", "", len(items)))

        # 解析 extra_json
        extra = {}
        try:
            extra = json.loads(c['extra_json'] or '{}')
        except (json.JSONDecodeError, TypeError):
            pass

        # 按消耗品类型显示特殊属性
        items.append(self.make_item("  消耗品效果:", "", len(items)))
        if ct == "fighter":
            fn = self.resolve_name("plane", extra.get('fighterName', '') or c.get('fighter_name', '') or '未知')
            items.append(self.make_item(f"    战斗机: {fn}", "", len(items)))
            items.append(self.make_item(f"    数量: {c['fighter_num'] or 0} | 截击机: {'是' if c['is_interceptor'] else '否'}", "", len(items)))
            if extra.get('dogFightTime'):
                items.append(self.make_item(f"    狗斗: {extra['dogFightTime']}s | 离开: {extra.get('flyAwayTime', 0)}s", "", len(items)))
            rk = extra.get('radiusToKill')
            if rk:
                items.append(self.make_item(f"    巡逻半径: {rk/10:.1f}km", "", len(items)))
        elif ct == "scout":
            dc = (extra.get('gunsDistCoeff') or 1) - 1
            items.append(self.make_item(f"    主炮射程: {dc*100:+.2f}%", "", len(items)))
        elif ct == "smokeGenerator":
            r = extra.get('radius', 0)
            items.append(self.make_item(f"    烟雾半径: {r*3:.0f}m | 高度: {extra.get('height', 0)}m", "", len(items)))
            items.append(self.make_item(f"    速度限制: {extra.get('speedLimit', 0)}kts | 扩散: {extra.get('lifeTime', 0)}s", "", len(items)))
        elif ct == "speedBoosters":
            bc = (extra.get('boostCoeff') or 1) - 1
            items.append(self.make_item(f"    最高航速: {bc*100:+.0f}%", "", len(items)))
            fe = (extra.get('forwardEngForsag') or 1) - 1
            be = (extra.get('backwardEngForsag') or 1) - 1
            items.append(self.make_item(f"    推力: 前进{fe*100:+.0f}% / 后退{be*100:+.0f}%", "", len(items)))
        elif ct == "sonar":
            ds = (extra.get('distShip') or 0) * 0.03
            dt = (extra.get('distTorpedo') or 0) * 0.03
            items.append(self.make_item(f"    舰船探测: {ds:.2f} km", "", len(items)))
            items.append(self.make_item(f"    鱼雷探测: {dt:.2f} km", "", len(items)))
            dm = (extra.get('distMine') or 0) * 0.03
            if dm:
                items.append(self.make_item(f"    水雷探测: {dm:.2f} km", "", len(items)))
        elif ct == "torpedoReloader":
            items.append(self.make_item(f"    鱼雷装填时间: {extra.get('torpedoReloadTime', 0)}s", "", len(items)))
        elif ct == "rls":
            ds = (extra.get('distShip') or 0) * 0.03
            items.append(self.make_item(f"    舰船探测: {ds:.2f} km", "", len(items)))
            aff = extra.get('affectedClasses', [])
            if aff:
                cls_str = ', '.join(NM.SHIP_CLASS_MAP.get(c, c) for c in aff)
                items.append(self.make_item(f"    限制探测舰种: {cls_str}", "", len(items)))
        elif ct == "artilleryBoosters":
            bc = (extra.get('boostCoeff') or 1) - 1
            items.append(self.make_item(f"    主炮装填时间: {bc*100:+.0f}%", "", len(items)))
        elif ct == "depthCharges":
            r = extra.get('radius', 0) * 0.003
            items.append(self.make_item(f"    半径: {r:.2f}km", "", len(items)))
        elif ct == "hydrophone":
            items.append(self.make_item(f"    虚影存留: {extra.get('zoneLifeTime', 0)}s | 刷新: {extra.get('hpUpdFreq', 0)}s", "", len(items)))
            wr = (extra.get('hpWaveRadius') or 0) * 0.001
            items.append(self.make_item(f"    视野距离: {wr:.2f}km", "", len(items)))
        elif ct == "fastRudders":
            brt = (extra.get('buoyancyRudderTimeCoeff') or 1) - 1
            bsc = (extra.get('maxBuoyancySpeedCoeff') or 1) - 1
            items.append(self.make_item(f"    水平舵换挡: {brt*100:+.0f}%", "", len(items)))
            items.append(self.make_item(f"    上浮/下潜速度: {bsc*100:+.0f}%", "", len(items)))
        elif ct == "subsEnergyFreeze":
            items.append(self.make_item(f"    启用后下潜能力将停止消耗", "", len(items)))
            items.append(self.make_item(f"    可在电池耗尽时启用: {'是' if extra.get('canUseOnEmpty') else '否'}", "", len(items)))
        elif ct == "submarineLocator":
            ds = (extra.get('distShip') or 0) * 0.03
            items.append(self.make_item(f"    舰船探测: {ds:.2f} km", "", len(items)))
        elif ct == "planeSmokeGenerator":
            items.append(self.make_item(f"    生效延迟: {extra.get('activationDelay', 0)}s", "", len(items)))
            r = extra.get('radius', 0) * 3
            items.append(self.make_item(f"    烟雾半径: {r:.0f}m", "", len(items)))
        elif ct == "supportBuoy":
            items.append(self.make_item(f"    区域: {extra.get('battleDropVisualName', '未知')}", "", len(items)))
            items.append(self.make_item(f"    布置时间: {extra.get('battleDropActTime', 0)}s", "", len(items)))
            items.append(self.make_item(f"    持续时间: {extra.get('supportBuoyZoneLifetime', 0)}s", "", len(items)))
        elif ct == "vampireDamage":
            coeff = (extra.get('damageGMHealCoeff') or 0) * 100
            items.append(self.make_item(f"    伤害转化系数: {coeff:.2f}%", "", len(items)))
        elif ct == "massHeal":
            hp = (extra.get('ownHealPart') or 0) * 100
            radius = (extra.get('workRadius') or 0) * 3 / 100
            items.append(self.make_item(f"    自身每秒回复: {hp:.1f}%", "", len(items)))
            items.append(self.make_item(f"    友军增益: {extra.get('allyBuffName', '')} Lv.{extra.get('allyBuffLevel', 1)}", "", len(items)))
            items.append(self.make_item(f"    作用半径: {radius:.2f}km", "", len(items)))
        else:
            # 未知类型：显示原始 extra_json 便于调试
            if c['area_dmg_multiplier']:
                items.append(self.make_item(f"    范围伤害倍率: {c['area_dmg_multiplier']}", "", len(items)))
            if c['bubble_dmg_multiplier']:
                items.append(self.make_item(f"    黑云伤害倍率: {c['bubble_dmg_multiplier']}", "", len(items)))
            if c['regen_hp_speed']:
                items.append(self.make_item(f"    每秒回复: {c['regen_hp_speed']} HP", "", len(items)))
            if extra:
                items.append(self.make_item(f"    其他参数: {json.dumps(extra, ensure_ascii=False)}", "", len(items)))

        return {
            "title": c['display_name'] or cid,
            "subtitle": f"ID: {cid}",
            "sections": [self.make_section("详情", items)],
        }
