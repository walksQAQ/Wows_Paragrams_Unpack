"""
ShipPresenter —— 从结构化数据库表组装舰船显示数据（新架构）。
"""

from __future__ import annotations

import json
import re
from collections import Counter

from presenters.base_presenter import BasePresenter, NM
from models.name_mapping import Mapping


class ShipPresenter(BasePresenter):
    """将舰船数据库记录组装为显示结构"""

    def build(self, ship_id: str, version_code: str = "") -> dict | None:
        try:
            return self._do_build(ship_id, version_code)
        except Exception as e:
            import traceback
            from app.signals import bus
            traceback.print_exc()
            bus.log_message.emit(f"⚠️ [ShipPresenter] {ship_id} 构建失败: {e}")
            return None

    def _do_build(self, ship_id: str, version_code: str = "") -> dict | None:
        sections: list[dict] = []
        conn = self.conn
        vc = self._ensure_version(version_code)

        # ── 1. 基础属性 ────────────────────────────────────
        basic = conn.execute(
            "SELECT * FROM ship_basic_info WHERE version_code=? AND ship_id=?", (vc, ship_id)).fetchone()
        if not basic:
            return None

        ship_name = self.resolve_name_by_id(basic['name_mapping_id'], 'ship', basic['ship_index']) or ship_id
        items = [
            self.make_item(f"  舰船名称: {ship_name}", "", 0),
            self.make_item(f"  编号: {basic['ship_index'] or ship_id.split('_')[0]}", "", 1),
        ]
        for k, label, etype in [("shiptype", "舰种", "ship_class"), ("tier", "等级", ""), ("group_status_key", "状态", "ship_group")]:
            if basic[k]:
                val = self.resolve_enum(etype, basic[k]) if etype else basic[k]
                items.append(self.make_item(f"  {label}: {val}", "", len(items)))

        # parent_ship / origin_ship — 提取编号前缀后再映射中文名
        for k, label in [("parent_ship_id", "原型舰船"), ("origin_ship_id", "原型舰船")]:
            if basic[k]:
                raw = basic[k].split("_")[0]  # PASA538_Hornet → PASA538
                pname = self.resolve_name('ship', raw)
                items.append(self.make_item(f"  {label}: {pname}", "", len(items)))
        sections.append(self.make_section("基础属性", items))

        # ── 2. 消耗品数据 ─────────────────────────────────
        self._append_consumables(conn, vc, ship_id, sections)

        # ── 3. 战斗指令 ───────────────────────────────────
        self._append_rage_mode(conn, vc, ship_id, sections)

        # ── 4. 各类型模块数据 ────────────────────────────
        self._aircraft_sub_info = {}
        self._append_modules(conn, vc, ship_id, sections)

        # ── 5. 构建子 section 信息 ───────────────────────
        sub_info = self._build_sub_section_info(conn, vc, ship_id, sections)
        if self._aircraft_sub_info:
            sub_info.update(self._aircraft_sub_info)

        return {
            "title": ship_name,
            "subtitle": f"ID: {ship_id}",
            "sections": sections,
            "extra": {"sub_sections": sub_info} if sub_info else {},
        }

    # ── 辅助 ───────────────────────────────────────────────

    @staticmethod
    def _config_group_letter(config_group: str) -> str:
        """从 config_group (如 'AB1', 'A') 提取首字母"""
        return config_group[0] if config_group else "?"

    @staticmethod
    def _append_strafe_time(lines: list, seq_json: str) -> None:
        """解析 attack_sequence_durations JSON 数组并显示扫射时序"""
        try:
            import json
            seq = json.loads(seq_json) if isinstance(seq_json, str) else seq_json
            if not isinstance(seq, (list, tuple)) or len(seq) < 2:
                return
            total = sum(seq)
            lines.append(f"        扫射时间: {total:.1f}s")
        except Exception:
            pass

    @staticmethod
    def _append_skip_data(lines: list, row) -> None:
        """显示跳弹数据：弹跳次数、最大触发角度"""
        import json
        try:
            skips_raw = row['skips_json']
            if not skips_raw:
                return
            skips = json.loads(skips_raw) if isinstance(skips_raw, str) else skips_raw
            if isinstance(skips, (list, tuple)):
                skip_count = len(skips)
                lines.append(f"        弹跳次数: {skip_count} 次")
                lines.append(f"        总共落点段数: {skip_count + 1} 段")
            if row['max_skip_angle']:
                lines.append(f"        最大弹跳触发角度: {row['max_skip_angle']:.0f}°")
        except Exception:
            pass

    @staticmethod
    def _append_ammo_pen(lines: list, row, ammo_type: str) -> None:
        """根据弹药类型显示穿深或硬度（row 为 sqlite3.Row，仅支持 [] 访问）"""
        try:
            if ammo_type == "HE":
                v = row['alpha_piercing_he']
                if v: lines.append(f"        穿深: {v:.1f} mm")
            elif ammo_type == "CS":
                v = row['alpha_piercing_cs']
                if v: lines.append(f"        穿深: {v:.1f} mm")
            elif ammo_type == "AP":
                v = row['bullet_krupp']
                if v: lines.append(f"        硬度: {v:.0f}")
            else:
                v = row['bullet_krupp']
                if v: lines.append(f"        穿深: {v:.0f}")
        except (KeyError, IndexError, TypeError):
            pass

    @staticmethod
    def _append_ammo_extra(lines: list, row, ammo_type: str) -> None:
        """AP/CS 专属属性：阻力系数、口径、跳弹角、引信等"""
        if ammo_type not in ("AP", "CS"):
            return
        try:
            if row['bullet_air_drag']:
                lines.append(f"        阻力系数: {row['bullet_air_drag']}")
            if row['bullet_diameter']:
                lines.append(f"        口径: {row['bullet_diameter']*1000:.2f} mm")
            if row['bullet_always_ricochet_at']:
                lines.append(f"        强制跳弹角: {row['bullet_always_ricochet_at']:.0f}°")
            if row['bullet_ricochet_at']:
                lines.append(f"        概率跳弹角: {row['bullet_ricochet_at']:.0f}°")
            if row['bullet_cap_normalize_max']:
                lines.append(f"        弹头转正角: {row['bullet_cap_normalize_max']:.0f}°")
            if ammo_type == "AP":
                if row['bullet_detonator']:
                    lines.append(f"        引信长度: {row['bullet_detonator']:.0f} s")
                if row['bullet_detonator_threshold']:
                    lines.append(f"        引信触发阈值: {row['bullet_detonator_threshold']:.0f} mm")
        except (KeyError, IndexError, TypeError):
            pass

    def _append_consumables(self, conn, vc, ship_id, sections):
        slots = conn.execute(
            "SELECT * FROM ship_consumable_slots WHERE version_code=? AND ship_id=? ORDER BY slot_index, item_index",
            (vc, ship_id)).fetchall()
        if not slots:
            return
        items = []
        last_slot = None
        for s in slots:
            if s['slot_index'] != last_slot:
                if last_slot is not None:
                    items.append(self.make_item(f"      {'─' * 20}", "", len(items)))
                items.append(self.make_item(f"  第 {s['slot_index']} 槽位:", "", len(items)))
                last_slot = s['slot_index']
            cname = self.resolve_name_by_id(s['display_name_id'], 'consumable', s['consumable_id']) or s['consumable_id'] or ""
            items.append(self.make_item(f"    ({s['item_index']}) {cname}", "", len(items)))
            # 从 consumable_configs 查找详细数据
            cfg = conn.execute(
                "SELECT * FROM consumable_configs WHERE version_code=? AND consumable_id=? AND config_key=?",
                (vc, s['consumable_id'], s['config_key'])).fetchone()
            if not cfg:
                cfg = conn.execute(
                    "SELECT * FROM consumable_configs WHERE version_code=? AND consumable_id=? AND config_key='Default'",
                    (vc, s['consumable_id'])).fetchone()
            if cfg:
                cfgd = dict(cfg)
                # 合并 extra_json（新版 schema 所有字段都在这里）
                ej = cfgd.pop('extra_json', None)
                if ej:
                    try:
                        extra = json.loads(ej)
                        cfgd.update(extra)
                    except (json.JSONDecodeError, TypeError):
                        pass
                ct = cfgd.get('consumableType') or cfgd.get('consumable_type') or ""
                num_raw = cfgd.get('numConsumables') or cfgd.get('num_consumables') or "0"
                prep = float(cfgd.get('preparationTime', 0) or 0)
                cd_time = float(cfgd.get('reloadTime', 0) or 0)
                wt = float(cfgd.get('workTime', 0) or 0)
                auto = cfgd.get('isAutoConsumable', False)
                items.append(self.make_item(f"        类型: {ct}", "", len(items)))
                if num_raw not in ('0', 0):
                    items.append(self.make_item(f"        数量: {'无限' if str(num_raw)=='-1' else str(num_raw)}", "", len(items)))
                if auto:
                    items.append(self.make_item(f"        自动使用: 是", "", len(items)))
                if prep:
                    items.append(self.make_item(f"        准备时间: {prep}s", "", len(items)))
                if cd_time:
                    items.append(self.make_item(f"        冷却时间: {cd_time}s", "", len(items)))
                if wt:
                    items.append(self.make_item(f"        持续时间: {wt}s", "", len(items)))
                items.append(self.make_item(f"        消耗品效果:", "", len(items)))
                # 按类型显示特有属性
                if ct == "crashCrew":
                    items.append(self.make_item(f"          扑灭起火、清除进水、并修复受损配件。", "", len(items)))
                elif ct == "fighter":
                    fn = cfgd.get('fightersName') or ""
                    if fn:
                        fname = self.resolve_name('plane', fn) or fn
                        items.append(self.make_item(f"          战斗机名称: {fname}", "", len(items)))
                    fn2 = cfgd.get('fightersNum') or 0
                    is_inter = cfgd.get('isInterceptor') or 0
                    items.append(self.make_item(f"          数量: {fn2} | 截击机: {'是' if is_inter else '否'}", "", len(items)))
                    dog = cfgd.get('dogFightTime', 0)
                    fly = cfgd.get('flyAwayTime', 0)
                    if dog or fly:
                        items.append(self.make_item(f"          狗斗: {dog}s | 离开: {fly}s", "", len(items)))
                    rk = cfgd.get('distanceToKill', 0)
                    if rk:
                        items.append(self.make_item(f"          巡逻半径: {rk/10:.2f}km", "", len(items)))
                elif ct == "scout":
                    dc = (float(cfgd.get('artilleryDistCoeff', 0) or 1) - 1)
                    items.append(self.make_item(f"          主炮射程: {dc*100:+.2f}%", "", len(items)))
                    modifiers = cfgd.get('modifiers')
                    if modifiers and isinstance(modifiers, dict):
                        for mk, mv in sorted(modifiers.items()):
                            label = Mapping.MODIFIER_MAP.get(mk, mk)
                            items.append(self.make_item(f"          {label}: {(mv-1)*100:+.0f}%", "", len(items)))
                elif ct == "smokeGenerator":
                    r = float(cfgd.get('radius', 0) or 0)
                    items.append(self.make_item(f"          烟雾半径: {r*3:.2f}m", "", len(items)))
                    h = cfgd.get('height', 0)
                    if h: items.append(self.make_item(f"          烟雾高度: {h}m", "", len(items)))
                    sp = cfgd.get('speedLimit', 0)
                    lt = cfgd.get('lifeTime', 0)
                    if sp or lt:
                        items.append(self.make_item(f"          速度限制: {sp}kts | 扩散: {lt}s", "", len(items)))
                elif ct == "speedBoosters":
                    bc = float(cfgd.get('boostCoeff', 0) or 0)
                    items.append(self.make_item(f"          最高航速: {bc*100:+.2f}%", "", len(items)))
                    fef = cfgd.get('forwardEngineForsag', 0)
                    bef = cfgd.get('backwardEngineForsag', 0)
                    if fef or bef:
                        items.append(self.make_item(f"          推力: 前进{fef*100:+.0f}% / 后退{bef*100:+.0f}%", "", len(items)))
                elif ct == "sonar":
                    ds = float(cfgd.get('distShip', 0) or 0) * 0.03
                    dt = float(cfgd.get('distTorpedo', 0) or 0) * 0.03
                    dm = float(cfgd.get('distSeaMine', 0) or 0) * 0.03
                    items.append(self.make_item(f"          舰船探测: {ds:.2f} km", "", len(items)))
                    if dt: items.append(self.make_item(f"          鱼雷探测: {dt:.2f} km", "", len(items)))
                    if dm: items.append(self.make_item(f"          水雷探测: {dm:.2f} km", "", len(items)))
                elif ct == "torpedoReloader":
                    trt = cfgd.get('torpedoReloadTime', 0)
                    if trt:
                        items.append(self.make_item(f"          鱼雷装填时间: {trt}s", "", len(items)))
                elif ct == "rls":
                    ds = float(cfgd.get('distShip', 0) or 0) * 0.03
                    items.append(self.make_item(f"          舰船探测: {ds:.2f} km", "", len(items)))
                    ac_classes = cfgd.get('affectedClasses', [])
                    if ac_classes:
                        cls_str = ', '.join(ac_classes)
                        items.append(self.make_item(f"          限制探测舰种: {cls_str}", "", len(items)))
                elif ct == "artilleryBoosters":
                    bc = (float(cfgd.get('boostCoeff', 0) or 1) - 1)
                    items.append(self.make_item(f"          主炮装填时间: {bc*100:+.2f}%", "", len(items)))
                elif ct == "depthCharges":
                    r = float(cfgd.get('radius', 0) or 0) * 0.003
                    items.append(self.make_item(f"          半径: {r:.2f}km", "", len(items)))
                elif ct == "regenCrew":
                    rr = cfgd.get('regenerationHPSpeed', 0) or cfgd.get('regenerationRate', 0)
                    if rr:
                        items.append(self.make_item(f"          每秒回复血量: {'+' if rr > 0 else ''}{rr*100:.2f}%", "", len(items)))
                elif ct == "airDefenseDisp":
                    adm = cfgd.get('areaDamageMultiplier', 0)
                    bdm = cfgd.get('bubbleDamageMultiplier', 0)
                    if adm: items.append(self.make_item(f"          防空区域秒伤: {adm*100:+.2f}%", "", len(items)))
                    if bdm: items.append(self.make_item(f"          黑云伤害: {bdm*100:+.2f}%", "", len(items)))
                elif ct == "hydrophone":
                    zlt = cfgd.get('zoneLifeTime', 0)
                    huf = cfgd.get('hydrophoneUpdateFrequency', 0)
                    hwr = cfgd.get('hydrophoneWaveRadius', 0)
                    if zlt: items.append(self.make_item(f"          虚影存留: {zlt}s", "", len(items)))
                    if huf: items.append(self.make_item(f"          刷新: {huf}s", "", len(items)))
                    if hwr: items.append(self.make_item(f"          视野距离: {hwr*0.001:.2f}km", "", len(items)))
                elif ct == "fastRudders":
                    brt = (float(cfgd.get('buoyancyRudderTimeCoeff', 0) or 1) - 1)
                    bsc = (float(cfgd.get('maxBuoyancySpeedCoeff', 0) or 1) - 1)
                    items.append(self.make_item(f"          水平舵换挡: {brt*100:+.2f}%", "", len(items)))
                    if bsc: items.append(self.make_item(f"          上浮/下潜速度: {bsc*100:+.2f}%", "", len(items)))
                elif ct == "subsEnergyFreeze":
                    items.append(self.make_item(f"          启用后下潜能力将停止消耗", "", len(items)))
                    cue = cfgd.get('canUseOnEmpty', False)
                    items.append(self.make_item(f"          可在电池耗尽时启用: {'是' if cue else '否'}", "", len(items)))
                elif ct == "submarineLocator":
                    ds = float(cfgd.get('distShip', 0) or 0) * 0.03
                    items.append(self.make_item(f"          舰船探测: {ds:.2f} km", "", len(items)))
                elif ct == "planeSmokeGenerator":
                    ad = cfgd.get('activationDelay', 0)
                    r = float(cfgd.get('radius', 0) or 0)
                    if ad: items.append(self.make_item(f"          生效延迟: {ad}s", "", len(items)))
                    if r: items.append(self.make_item(f"          烟雾半径: {r*3:.2f}m", "", len(items)))
                elif ct == "supportBuoy":
                    bdv = cfgd.get('battleDropVisualName', 'Unknown')
                    bda = cfgd.get('battleDropActivationTime', 0)
                    zlt = cfgd.get('zoneLifetime', 0)
                    items.append(self.make_item(f"          区域: {bdv}", "", len(items)))
                    if bda: items.append(self.make_item(f"          布置时间: {bda}s", "", len(items)))
                    if zlt: items.append(self.make_item(f"          持续时间: {zlt}s", "", len(items)))
                elif ct == "vampireDamage":
                    dgm = cfgd.get('damageGMHealCoeff', 0)
                    if dgm: items.append(self.make_item(f"          伤害转化系数: {dgm*100:.2f}%", "", len(items)))
                elif ct == "massHeal":
                    ohp = cfgd.get('ownHealPart', 0)
                    if ohp: items.append(self.make_item(f"          自身每秒回复: {ohp*100:.2f}%", "", len(items)))
                    wr = cfgd.get('workRadius', 0)
                    if wr: items.append(self.make_item(f"          回复作用半径: {wr*3/100:.2f} km", "", len(items)))
                    abn = cfgd.get('allyBuffName', '')
                    abl = cfgd.get('allyBuffLevel', 1)
                    if abn:
                        items.append(self.make_item(f"          友军增益: {abn} (等级{abl})", "", len(items)))
        if last_slot is not None:
            items.append(self.make_item(f"      {'─' * 20}", "", len(items)))
        sections.append(self.make_section("消耗品数据", items))

    # ── 战斗指令 ───────────────────────────────────────────

    def _append_rage_mode(self, conn, vc, ship_id, sections):
        rage = conn.execute(
            "SELECT * FROM ship_rage_mode WHERE version_code=? AND ship_id=?", (vc, ship_id)).fetchone()
        if not rage:
            return
        items = []
        o = 0
        dname = self.resolve_name_by_id(rage['display_name_id'], 'rage_mode', rage['rage_mode_name']) or "战斗指令"
        items.append(self.make_item(f"  === {dname} ===", "", o)); o += 1
        items.append(self.make_item(f"    持续时间: {rage['boost_duration']}s", "", o)); o += 1
        max_ac = rage['max_activation_count']
        items.append(self.make_item(f"    最大激活次数: {'无限' if max_ac=='-1' else f'{max_ac} 次'}", "", o)); o += 1
        items.append(self.make_item(f"    自动激活: {'是' if rage['is_auto_usage'] else '否'}", "", o)); o += 1
        items.append(self.make_item(f"    常驻生效: {'是' if rage['is_modifier_works_always'] else '否'}", "", o)); o += 1

        if rage['decrement_delay']:
            items.append(self.make_item(f"    衰减倒计时: {rage['decrement_delay']}s", "", o)); o += 1
            items.append(self.make_item(f"    衰减周期: {rage['decrement_period']}s", "", o)); o += 1
            items.append(self.make_item(f"    衰减数值: {rage['decrement_count']}%", "", o)); o += 1

        TRIGGER_LABELS = {
            "GameLogicTriggerOnActivation": "触发效果",
            "GameLogicTriggerProgress": "进度积累",
            "GameLogicTrigger": "进度积累",
        }

        triggers = json.loads(rage['triggers_json'] or '[]')
        if triggers:
            for trig_obj in triggers:
                for tkey, tdata in trig_obj.items():
                    trigger_label = TRIGGER_LABELS.get(tkey, tkey)
                    items.append(self.make_item(f"    [{trigger_label}]", "", o)); o += 1
                    act = tdata.get("Activator", {})
                    if act:
                        atype = act.get("type", "Unknown")
                        items.append(self.make_item(f"    激活: {atype}", "", o)); o += 1
                        for ak, av in act.items():
                            if ak == "type": continue
                            if ak in ("subRibbons", "triggerRibbonsTypes") and isinstance(av, list):
                                names = [NM.RIBBON_MAP.get(str(rid), str(rid)) for rid in av]
                                items.append(self.make_item(f"      - 所需勋带: {', '.join(names)}", "", o)); o += 1
                            elif ak == "requiredCount":
                                items.append(self.make_item(f"      - 所需次数: {av}", "", o)); o += 1
                            elif ak == "separateTracking":
                                items.append(self.make_item(f"      - 独立追踪: {'是' if av else '否'}", "", o)); o += 1
                            elif ak == "stateName":
                                items.append(self.make_item(f"      - 状态: {av}", "", o)); o += 1
                            else:
                                label = NM.DETAIL_MAP.get(ak, ak)
                                items.append(self.make_item(f"      - {label}: {av}", "", o)); o += 1
                    # 执行动作
                    actions_found = {k: v for k, v in tdata.items() if k.startswith("Action") and isinstance(v, dict)}
                    if actions_found:
                        for action_key, aln in actions_found.items():
                            atype = aln.get("type", "Unknown")
                            items.append(self.make_item(f"    动作: {atype}", "", o)); o += 1
                            for ak, av in aln.items():
                                if ak == "type": continue
                                if ak in ("planeId", "planeName"):
                                    pname = self.resolve_plane(av) or av
                                    items.append(self.make_item(f"      - 飞机型号: {pname}", "", o)); o += 1
                                elif ak == "progressName":
                                    items.append(self.make_item(f"      - 进度标识: {av}", "", o)); o += 1
                                else:
                                    label = NM.DETAIL_MAP.get(ak, ak)
                                    items.append(self.make_item(f"      - {label}: {av}", "", o)); o += 1

        # ── 加成效果 ──
        mods_raw = rage['modifiers_json']
        if mods_raw:
            try:
                mods = json.loads(mods_raw)
                if isinstance(mods, dict) and mods:
                    items.append(self.make_item(f"    加成效果:", "", o)); o += 1
                    for mk, mv in sorted(mods.items()):
                        label = Mapping.MODIFIER_MAP.get(mk, mk)
                        if isinstance(mv, dict):
                            # 分舰种加成
                            for species_key, factor in mv.items():
                                cn = NM.SHIP_CLASS_MAP.get(species_key, species_key)
                                items.append(self.make_item(f"      {cn}: {(factor - 1) * 100:+.0f}%", "", o)); o += 1
                        elif mk == "healthRegen":
                            items.append(self.make_item(f"      {label}: 每秒回复 {mv:.0f} HP", "", o)); o += 1
                        elif isinstance(mv, (float, int)):
                            if mv > 10.0:
                                items.append(self.make_item(f"      {label}: +{mv:.0f}", "", o)); o += 1
                            else:
                                items.append(self.make_item(f"      {label}: {(mv - 1) * 100:+.0f}%", "", o)); o += 1
                        else:
                            items.append(self.make_item(f"      {label}: {mv}", "", o)); o += 1
            except (json.JSONDecodeError, TypeError):
                pass

        sections.append(self.make_section("战斗指令", items))

    # ── 模块 ───────────────────────────────────────────────

    def _append_modules(self, conn, vc, ship_id, sections):
        # 获取所有配置组前缀字母
        letters = set()
        for tbl in ["ship_module_hulls", "ship_module_artillery", "ship_module_atba",
                      "ship_module_torpedoes", "ship_module_aa", "ship_module_depth_charge",
                      "ship_module_aircraft", "ship_module_air_support", "ship_module_engine"]:
            for r in conn.execute(
                f"SELECT DISTINCT config_group FROM {tbl} WHERE version_code=? AND ship_id=?",
                (vc, ship_id)).fetchall():
                letters.add(self._config_group_letter(r[0]))
        if not letters:
            return
        letters = sorted(letters)

        # 为每个字母收集各模块数据
        hull_data, arty_data, atba_data, torp_data = {}, {}, {}, {}
        aa_data, dc_data, plane_data, asup_data = {}, {}, {}, {}

        for letter in letters:
            self._build_hull(conn, vc, ship_id, letter, hull_data)
            self._build_artillery(conn, vc, ship_id, letter, arty_data)
            self._build_atba(conn, vc, ship_id, letter, atba_data)
            self._build_torpedoes(conn, vc, ship_id, letter, torp_data)
            self._build_aa(conn, vc, ship_id, letter, aa_data)
            self._build_depth_charge(conn, vc, ship_id, letter, dc_data)
            self._build_air_support(conn, vc, ship_id, letter, asup_data)

        for label, data in [("船体", hull_data), ("主炮", arty_data), ("副炮", atba_data),
                             ("鱼雷", torp_data), ("防空", aa_data), ("深水炸弹", dc_data)]:
            if data:
                all_lines = []
                for letter in letters:
                    letter_lines = data.get(letter, [])
                    if letter_lines:
                        if len(letters) > 1:
                            all_lines.append(f"──── {letter} 配置 ────")
                        all_lines.extend(letter_lines)
                if all_lines:
                    sections.append(self.make_section(label, [self.make_item("", "\n".join(all_lines), 0)]))
        # 舰载机独立处理：一个 section + 次级菜单
        plane_section = self._build_aircraft_panel(conn, vc, ship_id, letters, sections)
        if plane_section:
            sections.append(plane_section)
        # 空袭
        if asup_data:
            all_lines = []
            for letter in letters:
                letter_lines = asup_data.get(letter, [])
                if letter_lines:
                    if len(letters) > 1:
                        all_lines.append(f"──── {letter} 配置 ────")
                    all_lines.extend(letter_lines)
            if all_lines:
                sections.append(self.make_section("支援", [self.make_item("", "\n".join(all_lines), 0)]))

    # ── 模块构建子方法 ─────────────────────────────────────

    def _build_hull(self, conn, vc, ship_id, letter, result):
        lines = []
        # 查询舰种、等级、国家，用于最小隐蔽计算
        basic = conn.execute(
            "SELECT shiptype, tier, ship_index FROM ship_basic_info WHERE version_code=? AND ship_id=?",
            (vc, ship_id)).fetchone()
        species = basic['shiptype'] if basic else ""
        tier = basic['tier'] if basic else 0
        ship_idx = (basic['ship_index'] or ship_id.split("_")[0]) if basic else ship_id.split("_")[0]
        nat_row = conn.execute(
            "SELECT nation FROM entity_registry WHERE version_code=? AND entity_id=?",
            (vc, ship_id)).fetchone()
        nation = nat_row[0] if nat_row else ""

        # 隐蔽系数（参考 ship_analyzer.py get_conceal_coeff）
        if species == "Submarine":
            skill_bonus = 1.0
        elif species == "AirCarrier":
            skill_bonus = 0.85
        else:
            skill_bonus = 0.9
        upgrade_bonus = 1.0
        try:
            import json
            cfg = conn.execute(
                "SELECT ships_json, excludes_json, shiplevel_json, shiptype_json, nations_json, modifiers_json "
                "FROM modernization_basic_info WHERE version_code=? AND mod_id=?",
                (vc, "PCM027_ConcealmentMeasures_Mod_I")).fetchone()
            if cfg:
                mod_ships = json.loads(cfg['ships_json'] or '[]')
                mod_excludes = json.loads(cfg['excludes_json'] or '[]')
                mod_levels = json.loads(cfg['shiplevel_json'] or '[]')
                mod_types = json.loads(cfg['shiptype_json'] or '[]')
                mod_nations = json.loads(cfg['nations_json'] or '[]')
                is_whitelisted = any(s.startswith(ship_idx) for s in mod_ships)
                is_excluded = any(ex.startswith(ship_idx) for ex in mod_excludes)
                if is_whitelisted:
                    upgrade_bonus = 0.9
                elif not is_excluded and (tier in mod_levels and species in mod_types and nation in mod_nations):
                    upgrade_bonus = 0.9
        except Exception:
            pass
        conceal_coeff = skill_bonus * upgrade_bonus

        for h in conn.execute(
            "SELECT * FROM ship_module_hulls WHERE version_code=? AND ship_id=? AND config_group LIKE ? ORDER BY module_key",
            (vc, ship_id, f"{letter}%")).fetchall():
            for col, label in [
                ("health", "基础血量"), ("max_speed", "最大航速"),
                ("turning_radius", "转弯半径"), ("rudder_time", "转舵时间"),
                ("conceal_sea", "水面隐蔽"), ("conceal_air", "空中隐蔽"),
                ("has_citadel", "是否有核心区"), ("engine_power", "引擎马力"),
            ]:
                val = h[col]
                if val is not None:
                    if col == "has_citadel":
                        val = "是" if val else "否"
                    elif col == "max_speed":
                        val = f"{val:.2f} kts"
                    elif col == "health":
                        val = f"{val:.0f}"
                    elif col == "rudder_time":
                        val = f"{val:.2f} s"
                    elif col == "turning_radius":
                        val = f"{val:.2f} m"
                    elif col in ("conceal_sea", "conceal_air"):
                        val = f"{val:.2f} km"
                        lines.append(f"      {label}: {val}")
                        min_val = h[col] * conceal_coeff
                        min_label = "最小水面隐蔽" if col == "conceal_sea" else "最小空中隐蔽"
                        lines.append(f"         {min_label}: {min_val:.2f} km")
                        continue
                    elif col == "engine_power":
                        # 引擎马力前插入回复率
                        hrp = h['hull_regen_part']
                        crp = h['citadel_regen_part']
                        if hrp is not None or crp is not None:
                            hrp_str = f"{hrp*100:.2f}%" if hrp is not None else "N/A"
                            crp_str = f"{crp*100:.2f}%" if crp is not None else "N/A"
                            lines.append(f"      回复率: {hrp_str}/{crp_str}")
                        val = f"{val:.0f} HP"
                    elif isinstance(val, float):
                        val = f"{val:.2f}"
                    lines.append(f"      {label}: {val}")
            # 潜艇扩展数据
            ext = conn.execute(
                "SELECT * FROM ship_module_hulls_ext WHERE version_code=? AND ship_id=? AND config_group=? AND module_key=?",
                (vc, ship_id, h['config_group'], h['module_key'])).fetchone()
            if ext:
                if ext['battery_capacity'] is not None:
                    lines.append(f"      电池容量: {ext['battery_capacity']}")
                if ext['battery_regen'] is not None:
                    lines.append(f"      电力恢复: {ext['battery_regen']} /s")
                if ext['hydrophone_radius'] is not None:
                    lines.append(f"      水听器工作半径: {ext['hydrophone_radius']} km")
                if ext['hydrophone_update_freq'] is not None:
                    lines.append(f"      水听器更新周期: {ext['hydrophone_update_freq']} s")
                if ext['buoyancy_rudder_time'] is not None:
                    lines.append(f"      水平舵转舵时间: {ext['buoyancy_rudder_time']:.2f} s")
                if ext['max_buoyancy_speed'] is not None:
                    lines.append(f"      最大上浮/下潜速度: {ext['max_buoyancy_speed']:.2f} kts")
                # 深度状态
                depth_lines = []
                for ds in conn.execute(
                    "SELECT * FROM ship_sub_depth_states WHERE version_code=? AND ship_id=? AND config_group=? AND module_key=?",
                    (vc, ship_id, h['config_group'], h['module_key'])).fetchall():
                    cn_name = NM.DEPTH_MAP.get(ds['state_name'], ds['state_name'])
                    part = f"        {cn_name}: 航速×{ds['underwater_max_speed']}"
                    if ds['visibility_factor'] is not None:
                        part += f", 隐蔽×{ds['visibility_factor']}"
                    depth_lines.append(part)
                if depth_lines:
                    lines.append(f"      深度对航速影响：")
                    lines.extend(depth_lines)
        if lines:
            result[letter] = lines

    def _build_artillery(self, conn, vc, ship_id, letter, result):
        lines = []
        ammo_map = self.get_name_map("ammo")
        for g in conn.execute(
            "SELECT * FROM ship_module_artillery WHERE version_code=? AND ship_id=? AND config_group LIKE ? ORDER BY module_key",
            (vc, ship_id, f"{letter}%")).fetchall():
            gname = self.resolve_name('gun', g['module_key']) or g['module_key']
            lines.append(f"火炮名称: {gname} x{g['count']}")
            if g['num_barrels']: lines.append(f"联装数: {g['num_barrels']:.0f}")
            if g['reload_time']: lines.append(f"装填时间: {g['reload_time']}s")
            if g['max_range']: lines.append(f"基础射程: {g['max_range']:.2f} km")
            # 散步公式
            ir, mr, id_dist = g['ideal_radius'], g['min_radius'], g['ideal_distance']
            if ir and mr and id_dist:
                slope = (ir - mr) / (id_dist / 1000) if id_dist else 0
                intercept = mr * 30
                lines.append(f"横向散步公式: {slope:.2f}R + {intercept:.0f}")
            # 纵向散步
            if g['radius_zero'] is not None and g['radius_max'] is not None:
                r0, rdelim, rmax, delim = g['radius_zero'], g['radius_delim'], g['radius_max'], g['delim']
                pct = f"{delim*100:.0f}%" if delim else "?"
                lines.append(f"纵向散步系数: {r0} ~ {rdelim}(R={pct}) ~ {rmax}")
            if g['sigma']: lines.append(f"弹着群系数(Sigma): {g['sigma']}")
            # 弹药（含详细属性）
            seen = set()
            for swp in conn.execute(
                "SELECT DISTINCT ammo_id FROM ship_weapon_projectiles "
                "WHERE version_code=? AND ship_id=? AND module_id=? AND slot_type='artillery'",
                (vc, ship_id, g['module_key'])).fetchall():
                aid = swp["ammo_id"]
                if aid in seen:
                    continue
                seen.add(aid)
                acn = ammo_map.get(aid.upper(), aid)
                p = conn.execute(
                    "SELECT pb.species, pb.ammo_type, be.alpha_damage, be.bullet_krupp, "
                    "be.bullet_speed, be.explosion_radius, be.burn_prob, "
                    "be.bullet_mass, be.bullet_diameter, be.bullet_air_drag, "
                    "be.bullet_always_ricochet_at, be.bullet_ricochet_at, "
                    "be.bullet_detonator, be.bullet_detonator_threshold, be.bullet_cap_normalize_max "
                    "FROM projectile_basic_info pb "
                    "LEFT JOIN projectile_bullet_ext be ON be.version_code=pb.version_code AND be.projectile_id=pb.projectile_id "
                    "WHERE pb.version_code=? AND pb.projectile_id=?",
                    (vc, aid)).fetchone()
                if p:
                    at = (p['ammo_type'] or "").upper()
                    lines.append(f"可用炮弹: {acn}")
                    if p['alpha_damage']: lines.append(f"      标伤: {p['alpha_damage']:.0f}")
                    lines.append(f"      弹种: {p['ammo_type'] or '?'}")
                    lines.append(f"      炮弹详细属性:")
                    if p['explosion_radius']: lines.append(f"              炮弹爆炸半径: {p['explosion_radius']:.2f} m")
                    if p['bullet_diameter']: lines.append(f"              炮弹口径: {p['bullet_diameter']*1000:.0f} mm")
                    if p['bullet_speed']: lines.append(f"              炮弹初速: {p['bullet_speed']:.0f} m/s")
                    if p['bullet_air_drag']: lines.append(f"              空阻系数: {p['bullet_air_drag']}")
                    if p['bullet_mass']: lines.append(f"              炮弹重量: {p['bullet_mass']:.2f} kg")
                    if at == 'HE':
                        if p['burn_prob'] is not None: lines.append(f"              起火率: {p['burn_prob']*100:.2f}%")
                        if p['bullet_krupp']: lines.append(f"              HE穿深: {p['bullet_krupp']:.0f} mm")
                    elif at == 'SAP':
                        if p['bullet_krupp']: lines.append(f"              SAP穿深: {p['bullet_krupp']:.0f} mm")
                        rc1 = p['bullet_ricochet_at']
                        rc2 = p['bullet_always_ricochet_at']
                        if rc1 or rc2:
                            lines.append(f"              跳弹角度: {rc1:.0f}°/{rc2:.0f}°")
                    elif at == 'AP':
                        if p['bullet_krupp']: lines.append(f"              弹头硬度: {p['bullet_krupp']:.0f}")
                        if p['bullet_detonator'] is not None: lines.append(f"              引信触发阈值: {p['bullet_detonator']:.0f} mm")
                        if p['bullet_detonator_threshold']: lines.append(f"              引信长度: {p['bullet_detonator_threshold']:.2f} cal")
                        if p['bullet_cap_normalize_max']: lines.append(f"              炮弹转正角: {p['bullet_cap_normalize_max']:.2f}°")
                        rc1 = p['bullet_ricochet_at']
                        rc2 = p['bullet_always_ricochet_at']
                        if rc1 or rc2:
                            lines.append(f"              跳弹角度: {rc1:.0f}°/{rc2:.0f}°")
                else:
                    lines.append(f"可用炮弹: {acn}")
            # 特殊机制（弹夹/弹鼓炮）
            ext = conn.execute(
                "SELECT * FROM ship_module_artillery_ext WHERE version_code=? AND ship_id=? AND config_group=? AND module_key=?",
                (vc, ship_id, g['config_group'], g['module_key'])).fetchone()
            if ext and ext['special_mode_name']:
                sc = ext['drum_shots_count']
                sd = ext['drum_shot_delay']
                frt = ext['drum_full_reload_time']
                is_chargeable = ext['drum_is_chargeable']
                is_switchable = ext['drum_is_switchable']
                if is_chargeable:
                    header_name = "弹鼓炮"
                    details = [f"连发数量: {sc:.0f}", f"连发间隔: {sd}s"]
                    cmode = ext['drum_charge_mode']
                    cmin = ext['drum_charge_time_min']
                    cmax = ext['drum_charge_time_max']
                    if cmode == 1:
                        details.append(f"第 1 轮装填时间: {cmin}s")
                        details.append(f"第 2 ~ {sc:.0f} 轮装填时间: {cmax}s")
                    elif cmode == 2:
                        details.append(f"第 1 ~ {sc-1:.0f} 轮装填时间: {cmin}s")
                        details.append(f"第 {sc:.0f} 轮(末轮)装填时间: {cmax}s")
                else:
                    switch_prefix = "可切换" if is_switchable else "强制"
                    header_name = f"{switch_prefix}连发射击-弹夹炮"
                    details = [
                        f"长装填时间: {frt}s",
                        f"连发间隔: {sd}s",
                        f"连发轮数: {sc:.0f}"
                    ]
                lines.append(f"特殊机制: {header_name}")
                for d in details:
                    lines.append(f"  {d}")
                mods_raw = ext['drum_modifiers_json']
                if mods_raw and mods_raw != '{}':
                    try:
                        mods = json.loads(mods_raw)
                        if isinstance(mods, dict) and mods:
                            for mk, mv in sorted(mods.items()):
                                label = Mapping.MODIFIER_MAP.get(mk, mk)
                                lines.append(f"  {label}: {(mv-1)*100:+.0f}%")
                    except (json.JSONDecodeError, TypeError):
                        pass
        if lines:
            result[letter] = lines

    def _build_atba(self, conn, vc, ship_id, letter, result):
        lines = []
        ammo_map = self.get_name_map("ammo")
        for g in conn.execute(
            "SELECT * FROM ship_module_atba WHERE version_code=? AND ship_id=? AND config_group LIKE ? ORDER BY module_key",
            (vc, ship_id, f"{letter}%")).fetchall():
            gname = self.resolve_name('gun', g['module_key']) or g['module_key']
            lines.append(f"火炮名称: {gname} x{g['count']}")
            if g['num_barrels']: lines.append(f"联装数: {g['num_barrels']:.0f}")
            if g['reload_time']: lines.append(f"装填时间: {g['reload_time']}s")
            if g['max_range']: lines.append(f"基础射程: {g['max_range']:.2f} km")
            if g['sigma']: lines.append(f"弹着群系数(Sigma): {g['sigma']}")
            # 散步公式
            ir, mr, id_dist = g['ideal_radius'], g['min_radius'], g['ideal_distance']
            if ir and mr and id_dist:
                slope = (ir - mr) / (id_dist / 1000) if id_dist else 0
                intercept = mr * 30
                lines.append(f"横向散步公式: {slope:.2f}R + {intercept:.0f}")
            # 纵向散步
            if g['radius_zero'] is not None and g['radius_max'] is not None:
                r0, rdelim, rmax, delim = g['radius_zero'], g['radius_delim'], g['radius_max'], g['delim']
                pct = f"{delim*100:.0f}%" if delim else "?"
                lines.append(f"纵向散步系数: {r0} ~ {rdelim}(R={pct}) ~ {rmax}")
            seen = set()
            for swp in conn.execute(
                "SELECT DISTINCT ammo_id FROM ship_weapon_projectiles "
                "WHERE version_code=? AND ship_id=? AND module_id=? AND slot_type='atba'",
                (vc, ship_id, g['module_key'])).fetchall():
                aid = swp["ammo_id"]
                if aid in seen:
                    continue
                seen.add(aid)
                acn = ammo_map.get(aid.upper(), aid)
                p = conn.execute(
                    "SELECT pb.species, pb.ammo_type, be.alpha_damage, be.bullet_krupp, "
                    "be.bullet_speed, be.explosion_radius, be.burn_prob, "
                    "be.bullet_mass, be.bullet_diameter, be.bullet_air_drag, "
                    "be.bullet_always_ricochet_at, be.bullet_ricochet_at, "
                    "be.bullet_detonator, be.bullet_detonator_threshold, be.bullet_cap_normalize_max "
                    "FROM projectile_basic_info pb "
                    "LEFT JOIN projectile_bullet_ext be ON be.version_code=pb.version_code AND be.projectile_id=pb.projectile_id "
                    "WHERE pb.version_code=? AND pb.projectile_id=?",
                    (vc, aid)).fetchone()
                if p:
                    at = (p['ammo_type'] or "").upper()
                    lines.append(f"可用炮弹: {acn}")
                    if p['alpha_damage']: lines.append(f"      标伤: {p['alpha_damage']:.0f}")
                    lines.append(f"      弹种: {p['ammo_type'] or '?'}")
                    lines.append(f"      炮弹详细属性:")
                    if p['explosion_radius']: lines.append(f"              炮弹爆炸半径: {p['explosion_radius']:.2f} m")
                    if p['bullet_diameter']: lines.append(f"              炮弹口径: {p['bullet_diameter']*1000:.0f} mm")
                    if p['bullet_speed']: lines.append(f"              炮弹初速: {p['bullet_speed']:.0f} m/s")
                    if p['bullet_air_drag']: lines.append(f"              空阻系数: {p['bullet_air_drag']}")
                    if p['bullet_mass']: lines.append(f"              炮弹重量: {p['bullet_mass']:.2f} kg")
                    if at == 'HE':
                        if p['burn_prob'] is not None: lines.append(f"              起火率: {p['burn_prob']*100:.2f}%")
                        if p['bullet_krupp']: lines.append(f"              HE穿深: {p['bullet_krupp']:.0f} mm")
                    elif at == 'SAP':
                        if p['bullet_krupp']: lines.append(f"              SAP穿深: {p['bullet_krupp']:.0f} mm")
                        rc1 = p['bullet_ricochet_at']
                        rc2 = p['bullet_always_ricochet_at']
                        if rc1 or rc2:
                            lines.append(f"              跳弹角度: {rc1:.0f}°/{rc2:.0f}°")
                    elif at == 'AP':
                        if p['bullet_krupp']: lines.append(f"              弹头硬度: {p['bullet_krupp']:.0f}")
                        if p['bullet_detonator'] is not None: lines.append(f"              引信触发阈值: {p['bullet_detonator']:.0f} mm")
                        if p['bullet_detonator_threshold']: lines.append(f"              引信长度: {p['bullet_detonator_threshold']:.2f} cal")
                        if p['bullet_cap_normalize_max']: lines.append(f"              炮弹转正角: {p['bullet_cap_normalize_max']:.2f}°")
                        rc1 = p['bullet_ricochet_at']
                        rc2 = p['bullet_always_ricochet_at']
                        if rc1 or rc2:
                            lines.append(f"              跳弹角度: {rc1:.0f}°/{rc2:.0f}°")
                else:
                    lines.append(f"可用炮弹: {acn}")
        if lines:
            result[letter] = lines

    def _build_torpedoes(self, conn, vc, ship_id, letter, result):
        lines = []
        ammo_map = self.get_name_map("ammo")
        for t in conn.execute(
            "SELECT * FROM ship_module_torpedoes WHERE version_code=? AND ship_id=? AND config_group LIKE ? ORDER BY module_key",
            (vc, ship_id, f"{letter}%")).fetchall():
            tname = self.resolve_name('gun', t['module_key']) or t['module_key']
            lines.append(f"  - {tname} x{t['count']}")
            if t['reload_time']: lines.append(f"    装填时间: {t['reload_time']}s")
            seen = set()
            for swp in conn.execute(
                "SELECT DISTINCT ammo_id FROM ship_weapon_projectiles "
                "WHERE version_code=? AND ship_id=? AND module_id=? AND slot_type='torpedo'",
                (vc, ship_id, t['module_key'])).fetchall():
                aid = swp["ammo_id"]
                if aid in seen:
                    continue
                seen.add(aid)
                aname = ammo_map.get(aid.upper(), aid)
                p = conn.execute(
                    "SELECT pb.species, pb.custom_ui_postfix, te.alpha_damage, te.damage, te.torpedo_speed, "
                    "te.torpedo_max_dist, te.torpedo_visibility, te.torpedo_arming_time, "
                    "te.burn_prob, te.uw_critical, te.is_deep_water, te.flood_generation "
                    "FROM projectile_basic_info pb "
                    "LEFT JOIN projectile_torpedo_ext te ON te.version_code=pb.version_code AND te.projectile_id=pb.projectile_id "
                    "WHERE pb.version_code=? AND pb.projectile_id=?",
                    (vc, aid)).fetchone()
                if p:
                    postfix = p['custom_ui_postfix'] or ""
                    is_burn = postfix == "_subBurn"
                    is_deep = bool(p['is_deep_water'])
                    sge = conn.execute(
                        "SELECT search_radius, search_angle, max_yaw, max_vertical_speed, max_depth_level, target_lost_degradation_time "
                        "FROM projectile_torpedo_sub_guidance_ext WHERE version_code=? AND projectile_id=?",
                        (vc, aid)).fetchone()
                    is_guided = sge is not None
                    # 确定鱼雷类型标签（参考老代码逻辑）
                    if is_guided:
                        dtype = "声呐导向鱼雷"
                    elif is_deep:
                        dtype = "深水鱼雷"
                    elif is_burn:
                        dtype = "热能鱼雷"
                    else:
                        dtype = "鱼雷"
                    lines.append(f"    ── {aname} ({dtype}) ──")
                    ad = p['alpha_damage'] or 0
                    if ad: lines.append(f"      标伤: {ad * 0.33:.0f}")
                    if p['torpedo_speed']: lines.append(f"      航速: {p['torpedo_speed']:.0f} kts")
                    dist = p['torpedo_max_dist']
                    if dist: lines.append(f"      射程: {dist * 0.03:.2f} km")
                    if p['torpedo_visibility']: lines.append(f"      被发现距离: {p['torpedo_visibility']:.2f} km")
                    if p['torpedo_arming_time']: lines.append(f"      鱼雷上浮时间: {p['torpedo_arming_time']:.2f} s")
                    if p['flood_generation'] and p['uw_critical']:
                        lines.append(f"      基础漏水系数: {p['uw_critical']:.2f}")
                    # 热能鱼雷显示点火率
                    if is_burn and p['burn_prob']:
                        lines.append(f"      基础点火率: {p['burn_prob']*100:.0f}%")
                    # 声呐导向鱼雷专属数据
                    if sge:
                        if sge['search_radius']: lines.append(f"      搜索半径: {sge['search_radius']:.2f} km")
                        if sge['search_angle']: lines.append(f"      搜索角度: {sge['search_angle']:.0f}°")
                        if sge['max_yaw']: lines.append(f"      最大转向角: {sge['max_yaw']:.0f}°")
                        if sge['max_vertical_speed']: lines.append(f"      最大垂直速度: {sge['max_vertical_speed']:.2f} kts")
                        if sge['max_depth_level']: lines.append(f"      最大深度级别: {sge['max_depth_level']:.0f}")
                        if sge['target_lost_degradation_time']: lines.append(f"      丢失目标降级时间: {sge['target_lost_degradation_time']:.1f}s")
                else:
                    lines.append(f"    {aname}")
        if lines:
            result[letter] = lines

    def _build_aa(self, conn, vc, ship_id, letter, result):
        lines = []
        auras = {"Far": None, "Medium": None, "Near": None}
        bubble_data = {}
        guns = []
        seen_guns = set()
        for a in conn.execute(
            "SELECT * FROM ship_module_aa WHERE version_code=? AND ship_id=? AND config_group LIKE ?",
            (vc, ship_id, f"{letter}%")).fetchall():
            if a['aura_type'] in ('bubble', 'continuous'):
                atype = a['type'] or ""
                atype_key = atype.capitalize()
                if atype_key in ("Far", "Medium", "Near"):
                    if a['aura_type'] == 'bubble':
                        bubble_data = {
                            "dmg": a['bubble_damage'] or 0,
                            "hit": a['hit_chance'],
                            "max": a['max_distance'],
                            "min": a['min_distance'],
                            "count": a['explosion_count'] or 0,
                        }
                    else:
                        cur = auras[atype_key]
                        nd = a['aura_dps']
                        if cur is None or (nd is not None and nd > (cur[0] if isinstance(cur, tuple) else cur)):
                            auras[atype_key] = (nd, a['hit_chance'], a['max_distance'], a['min_distance'])
            if a['aa_gun_name'] and a['aa_gun_name'] not in seen_guns:
                seen_guns.add(a['aa_gun_name'])
                gname = self.resolve_name('gun', a['aa_gun_name']) or a['aa_gun_name']
                guns.append(f"{gname} * {a['aa_gun_count']}")
        if any(v is not None for v in auras.values()):
            lines.append(f"  持续伤害:")
            labels = {"Far": "远程", "Medium": "中程", "Near": "近程"}
            for key in ("Far", "Medium", "Near"):
                info = auras[key]
                if info is not None:
                    dps_val, hit_chance, max_d, min_d = info
                    lines.append(f"    {labels[key]}防空炮:")
                    lines.append(f"      伤害: {dps_val:.0f}")
                    if hit_chance is not None:
                        lines.append(f"      命中率: {hit_chance*100:.0f}%")
                    if min_d is not None and max_d is not None:
                        lines.append(f"      射程: {min_d:.0f} ~ {max_d:.0f} km")
        if bubble_data:
            lines.append(f"  防空炮弹:")
            bd = bubble_data["dmg"]
            if bd:
                lines.append(f"    爆炸伤害: {bd:.0f}")
            bc = bubble_data.get("hit")
            if bc is not None:
                lines.append(f"    命中率: {bc*100:.0f}%")
            bmin = bubble_data.get("min")
            bmax = bubble_data.get("max")
            if bmin is not None and bmax is not None:
                lines.append(f"    射程: {bmin:.0f} ~ {bmax:.0f} km")
            bcnt = bubble_data.get("count")
            if bcnt:
                lines.append(f"    一次齐射数量: {bcnt:.0f}")
        if guns:
            lines.append(f"  防空炮:")
            for g in guns:
                lines.append(f"    防空炮名称: {g}")
        if lines:
            result[letter] = lines

    def _build_depth_charge(self, conn, vc, ship_id, letter, result):
        lines = []
        for d in conn.execute(
            "SELECT * FROM ship_module_depth_charge WHERE version_code=? AND ship_id=? AND config_group LIKE ?",
            (vc, ship_id, f"{letter}%")).fetchall():
            gname = self.resolve_name('gun', d['gun_name']) or d['gun_name']
            lines.append(f"    - {gname} x{d['count']}")
            if d['reload_time']: lines.append(f"      装填时间: {d['reload_time']}s")
            if d['shot_delay']: lines.append(f"      发射间隔: {d['shot_delay']}s")
            if d['max_packs']: lines.append(f"      最大组数: {d['max_packs']}")
            if d['num_shots']: lines.append(f"      每组数量: {d['num_shots']}")
            if d['damage']: lines.append(f"      标伤: {d['damage']:.0f}")
            if d['dc_speed']: lines.append(f"      下沉速度: {d['dc_speed']:.2f} m/s")
            if d['dc_timer']: lines.append(f"      引信定时: {d['dc_timer']:.2f}s")
            if d['dc_max_depth']: lines.append(f"      最大深度: {d['dc_max_depth']:.0f} m")
            if d['depth_splash_size']: lines.append(f"      溅射范围: {d['depth_splash_size']:.2f} m")
        if lines:
            result[letter] = lines

    def _build_aircraft_panel(self, conn, vc, ship_id, letters, sections):
        """构建单一「舰载机」section，次级菜单按机种分 tab，tab 内按 config_prefix 分组"""
        # 收集所有飞机
        all_rows = []
        for letter in letters:
            for p in conn.execute(
                "SELECT * FROM ship_module_aircraft WHERE version_code=? AND ship_id=? AND config_group LIKE ?",
                (vc, ship_id, f"{letter}%")).fetchall():
                all_rows.append(dict(p))
        if not all_rows:
            self._aircraft_sub_info = {}
            return None

        TYPE_LABEL = {
            "Fighter": "攻击机", "DiveBomber": "俯冲轰炸机",
            "TorpedoBomber": "鱼雷轰炸机", "SkipBomber": "弹跳轰炸机",
        }
        # 按 plane_type 分组
        by_type: dict[str, list] = {}
        for r in all_rows:
            pt = r.get('plane_type') or '其他'
            by_type.setdefault(pt, []).append(r)

        # 构建次级菜单内容：sub_labels + sub_contents
        sub_labels: list[str] = []
        sub_contents: dict = {}
        for ptype in ("Fighter", "DiveBomber", "TorpedoBomber", "SkipBomber", "其他"):
            rows = by_type.get(ptype)
            if not rows:
                continue
            label = TYPE_LABEL.get(ptype, ptype)
            sub_labels.append(label)
            # 按 config_prefix 分组
            prefix_map: dict[str, list] = {}
            for r in rows:
                cg = r.get('config_group') or ""
                prefix_map.setdefault(cg, []).append(r)
            cg_keys = sorted(prefix_map.keys(), key=lambda x: (x == "", x))
            config_labels: list[str] = []
            config_contents: dict[str, list[str]] = {}
            for cg in cg_keys:
                cg_label = f"{cg} 配置"
                config_labels.append(cg_label)
                clines: list[str] = []
                group = prefix_map[cg]
                for p in group:
                    pn = p.get('plane_name', '')
                    display_name = self.resolve_plane(pn)
                    clines.append(f"      飞机型号: {display_name}")
                    # plane_basic_info
                    pi = conn.execute(
                        "SELECT * FROM plane_basic_info WHERE version_code=? AND plane_id=?",
                        (vc, self.resolve_plane_id(pn))).fetchone()
                    pid = {}
                    if pi:
                        pid = dict(pi)
                        if pid.get('plane_level'): clines.append(f"      飞机等级: {pid['plane_level']}")
                        # 速度（CV 飞机用 speed_move_with_bomb）
                        smwb = pid.get('speed_move_with_bomb')
                        if smwb:
                            max_mul = pid.get('speed_max_mult')
                            min_mul = pid.get('speed_min_mult')
                            clines.append(f"      巡航速度: {smwb} kts")
                            if max_mul:
                                clines.append(f"          最大速度: {smwb * max_mul:.2f} kts")
                            if min_mul:
                                clines.append(f"          最小速度: {smwb * min_mul:.2f} kts")
                        else:
                            if pid.get('max_speed'): clines.append(f"      航速: {pid['max_speed']} kts")
                            if pid.get('cruising_speed'): clines.append(f"      巡航速度: {pid['cruising_speed']} kts")
                        if pid.get('hp'): clines.append(f"      单架飞机血量: {pid['hp']}")
                        ac = pid.get('attack_count') or 0
                        ai = pid.get('attack_interval') or 0
                        if ac:
                            clines.append(f"      载弹量: {ac}")
                        if pid.get('attack_cooldown'): clines.append(f"      攻击冷却时间: {pid['attack_cooldown']}s")
                        if pid.get('arrange_size') and pid['arrange_size'] > 0:
                            clines.append(f"      中队规模: {pid['arrange_size']}")
                        # 角度
                        if pid.get('angle_of_climb'): clines.append(f"          爬升角度: {pid['angle_of_climb']}°")
                        if pid.get('angle_of_dive'): clines.append(f"          俯冲角度: {pid['angle_of_dive']}°")
                        if pid.get('attack_angle') is not None: clines.append(f"          攻击角度: {pid['attack_angle']}°")
                        # 散布/缩圈/时间
                        if pid.get('preparation_time'): clines.append(f"      准备时间: {pid['preparation_time']}s")
                        if pid.get('preparation_accel_increase') is not None:
                            clines.append(f"          准备缩圈速度: {pid['preparation_accel_increase']}")
                        if pid.get('preparation_accel_decrease') is not None:
                            clines.append(f"          准备扩圈速度: {abs(pid['preparation_accel_decrease'])}")
                        if pid.get('aiming_time'): clines.append(f"      瞄准时间: {pid['aiming_time']}s")
                        if pid.get('aiming_accel_increase') is not None:
                            clines.append(f"          瞄准缩圈速度: {pid['aiming_accel_increase']}")
                        if pid.get('aiming_accel_decrease') is not None:
                            clines.append(f"          瞄准扩圈速度: {abs(pid['aiming_accel_decrease'])}")
                        if pid.get('post_attack_invulnerability_duration'):
                            clines.append(f"      攻击后无敌时间: {pid['post_attack_invulnerability_duration']}s")
                        if pid.get('flight_height'): clines.append(f"      飞行高度: {pid['flight_height']}")
                        # 编队/燃料
                        if pid.get('attacker_size'): clines.append(f"      攻击编队大小: {pid['attacker_size']}")
                        if pid.get('num_planes_in_squadron'): clines.append(f"      中队飞机数量: {pid['num_planes_in_squadron']}")
                        if pid.get('visibility_factor') is not None: clines.append(f"      被侦测距离: {pid['visibility_factor']} km")
                        # 跳弹轰炸机专属
                        if pid.get('species') == "Skip":
                            if pid.get('skip_height') is not None: clines.append(f"      弹跳高度: {pid['skip_height']}")
                            if pid.get('aiming_height') is not None: clines.append(f"      瞄准视角高度: {pid['aiming_height']}")
                        # 散布计算（K=30.0 矩阵乘法公式）
                        oss_x = pid.get('outer_salvo_size_x')
                        oss_y = pid.get('outer_salvo_size_y')
                        iss_x = pid.get('inner_salvo_size_x')
                        iss_y = pid.get('inner_salvo_size_y')
                        maxs_x = pid.get('max_spread_x')
                        maxs_y = pid.get('max_spread_y')
                        mins_x = pid.get('min_spread_x')
                        mins_y = pid.get('min_spread_y')
                        ibp = pid.get('inner_bombs_percentage')
                        _K = 30.0
                        if all(v is not None for v in (oss_x, oss_y, iss_x, iss_y, maxs_x, maxs_y)):
                            # 分支 A：椭圆矩阵计算
                            mins_x = mins_x or 1.0
                            mins_y = mins_y or 1.0
                            def _rnd(v):
                                return int(v + 0.5)
                            min_outer = (_rnd(oss_x * mins_x * _K), _rnd(oss_y * mins_y * _K))
                            max_outer = (_rnd(oss_x * maxs_x * _K), _rnd(oss_y * maxs_y * _K))
                            min_inner = (_rnd(iss_x * mins_x * _K), _rnd(iss_y * mins_y * _K))
                            max_inner = (_rnd(iss_x * maxs_x * _K), _rnd(iss_y * maxs_y * _K))
                            if ibp is not None:
                                clines.append(f"      核心投弹: {int(ibp)}%")
                            clines.append(f"      散布相关:")
                            clines.append(f"          最大散布: {max_outer[0]}x{max_outer[1]}")
                            clines.append(f"          最小散布: {min_outer[0]}x{min_outer[1]}")
                            clines.append(f"              最大散布内圈: {max_inner[0]}x{max_inner[1]}")
                            clines.append(f"              最小散布内圈: {min_inner[0]}x{min_inner[1]}")
                        elif pid.get('max_spread') is not None:
                            # 分支 B：鱼雷轰炸机，显示单值散布
                            clines.append(f"      最大散布: {pid['max_spread']}")
                            if pid.get('min_spread') is not None:
                                clines.append(f"      最小散布: {pid['min_spread']}")
                        # 机库
                        clines.append(f"      机库:")
                        if pid.get('hangar_max_value') is not None:
                            clines.append(f"        最大可用数量: {pid['hangar_max_value']} 架")
                        if pid.get('hangar_start_value') is not None:
                            clines.append(f"        开局可用数量: {pid['hangar_start_value']} 架")
                        if pid.get('hangar_restore_amount') is not None:
                            clines.append(f"        每次整备数量: {pid['hangar_restore_amount']}架")
                        if pid.get('hangar_time_to_restore') is not None:
                            clines.append(f"        每次整备时间: {pid['hangar_time_to_restore']} s")
                        # 用 bomb_name 作为弹药回退
                        bname = pid.get('bomb_name') or ""
                    else:
                        ac = ai = 0
                        bname = ""
                    arm = p.get('armament_name') or ""
                    proj_id = arm or bname
                    if proj_id:
                        # 先查 projectile_basic_info 确定类型
                        pbi = conn.execute(
                            "SELECT species, ammo_type FROM projectile_basic_info WHERE version_code=? AND projectile_id=?",
                            (vc, proj_id)).fetchone()
                        if pbi:
                            species = pbi['species'] or ""
                            atype = pbi['ammo_type'] or ""
                            clines.append(f"      ── 弹药: {species} ({atype}) ──")
                            _ammo_cols = "alpha_damage, bullet_krupp, alpha_piercing_he, alpha_piercing_cs, bullet_speed, explosion_radius, burn_prob, bullet_diameter, bullet_air_drag, bullet_always_ricochet_at, bullet_ricochet_at, bullet_detonator, bullet_detonator_threshold, bullet_cap_normalize_max"
                            _bomb_ext_cols = f"damage, skips_json, max_skip_angle, {_ammo_cols}"
                            if species in ("Bullet", "HE"):
                                be = conn.execute(
                                    f"SELECT {_ammo_cols} "
                                    "FROM projectile_bullet_ext WHERE version_code=? AND projectile_id=?",
                                    (vc, proj_id)).fetchone()
                                if be:
                                    if be['alpha_damage']: clines.append(f"        标伤: {be['alpha_damage']:.0f}")
                                    self._append_ammo_pen(clines, be, atype)
                                    if be['bullet_speed']: clines.append(f"        弹速: {be['bullet_speed']:.0f} m/s")
                                    if be['explosion_radius']: clines.append(f"        爆炸半径: {be['explosion_radius']:.2f} m")
                                    if be['burn_prob'] is not None: clines.append(f"        起火概率: {be['burn_prob']*100:.2f}%")
                                    self._append_ammo_extra(clines, be, atype)
                            elif species == "Bomb":
                                be = conn.execute(
                                    f"SELECT {_bomb_ext_cols} "
                                    "FROM projectile_bomb_ext WHERE version_code=? AND projectile_id=?",
                                    (vc, proj_id)).fetchone()
                                if be:
                                    if be['alpha_damage']: clines.append(f"        标伤: {be['alpha_damage']:.0f}")
                                    self._append_ammo_pen(clines, be, atype)
                                    if be['bullet_speed']: clines.append(f"        弹速: {be['bullet_speed']:.0f} m/s")
                                    if be['explosion_radius']: clines.append(f"        爆炸半径: {be['explosion_radius']:.2f} m")
                                    if be['burn_prob'] is not None: clines.append(f"        起火概率: {be['burn_prob']*100:.2f}%")
                                    self._append_ammo_extra(clines, be, atype)
                                    self._append_skip_data(clines, be)
                            elif species == "SkipBomb":
                                be = conn.execute(
                                    f"SELECT {_bomb_ext_cols} "
                                    "FROM projectile_bomb_ext WHERE version_code=? AND projectile_id=?",
                                    (vc, proj_id)).fetchone()
                                if be:
                                    if be['alpha_damage']: clines.append(f"        标伤: {be['alpha_damage']:.0f}")
                                    self._append_ammo_pen(clines, be, atype)
                                    if be['bullet_speed']: clines.append(f"        弹速: {be['bullet_speed']:.0f} m/s")
                                    if be['explosion_radius']: clines.append(f"        爆炸半径: {be['explosion_radius']:.2f} m")
                                    if be['burn_prob'] is not None: clines.append(f"        起火概率: {be['burn_prob']*100:.2f}%")
                                    self._append_ammo_extra(clines, be, atype)
                                    self._append_skip_data(clines, be)
                            elif species == "Rocket":
                                re = conn.execute(
                                    f"SELECT damage, {_ammo_cols} "
                                    "FROM projectile_rocket_ext WHERE version_code=? AND projectile_id=?",
                                    (vc, proj_id)).fetchone()
                                if re:
                                    if re['alpha_damage']: clines.append(f"        标伤: {re['alpha_damage']:.0f}")
                                    self._append_ammo_pen(clines, re, atype)
                                    if re['bullet_speed']: clines.append(f"        弹速: {re['bullet_speed']:.0f} m/s")
                                    if re['explosion_radius']: clines.append(f"        爆炸半径: {re['explosion_radius']:.2f} m")
                                    if re['burn_prob'] is not None: clines.append(f"        起火概率: {re['burn_prob']*100:.2f}%")
                                    self._append_ammo_extra(clines, re, atype)
                                # 火箭弹额外读取扫射序列
                                asq = conn.execute(
                                    "SELECT attack_sequence_durations FROM projectile_rocket_ext WHERE version_code=? AND projectile_id=?",
                                    (vc, proj_id)).fetchone()
                                if asq and asq['attack_sequence_durations']:
                                    self._append_strafe_time(clines, asq['attack_sequence_durations'])
                            elif species in ("Torpedo", "TorpedoBomber"):
                                te = conn.execute(
                                    "SELECT alpha_damage, damage, torpedo_speed, torpedo_max_dist, torpedo_visibility, "
                                    "torpedo_arming_time, burn_prob, uw_critical, flood_generation, is_deep_water, deep_water_ignore_classes, alert_dist "
                                    "FROM projectile_torpedo_ext WHERE version_code=? AND projectile_id=?",
                                    (vc, proj_id)).fetchone()
                                if te:
                                    # 检测声导/深水/热能
                                    sge = conn.execute(
                                        "SELECT max_yaw, drop_dist_aircarrier, drop_dist_battleship, drop_dist_cruiser, "
                                        "drop_dist_destroyer, drop_dist_submarine, drop_dist_default "
                                        "FROM projectile_torpedo_sub_guidance_ext WHERE version_code=? AND projectile_id=?",
                                        (vc, proj_id)).fetchone()
                                    is_guided = sge is not None
                                    is_deep = te['is_deep_water']
                                    is_burn = bool(te['burn_prob'])
                                    if is_guided:
                                        dtype = "声呐导向鱼雷"
                                    elif is_deep:
                                        dtype = "深水鱼雷"
                                    elif is_burn:
                                        dtype = "热能鱼雷"
                                    else:
                                        dtype = "鱼雷"
                                    clines.append(f"        类型: {dtype}")
                                    ad = te['alpha_damage'] or 0
                                    if ad: clines.append(f"        标伤: {ad * 0.33:.0f}")
                                    if is_deep and te['deep_water_ignore_classes']:
                                        clines.append(f"        无法攻击目标: {te['deep_water_ignore_classes']}")
                                    if te['torpedo_speed']: clines.append(f"        航速: {te['torpedo_speed']:.0f} kts")
                                    if te['torpedo_max_dist'] is not None: clines.append(f"        最大射程: {(te['torpedo_max_dist'] * 30) / 1000:.2f} km")
                                    if te['flood_generation'] and te['uw_critical']:
                                        clines.append(f"        基础漏水系数: {te['uw_critical']:.2f}")
                                    if te['torpedo_visibility']: clines.append(f"        鱼雷被侦测距离: {te['torpedo_visibility']:.2f} km")
                                    if te['torpedo_arming_time']: clines.append(f"        鱼雷上浮时间: {te['torpedo_arming_time']:.2f} s")
                                    if is_burn and te['burn_prob']:
                                        clines.append(f"        基础点火率: {te['burn_prob']*100:.0f}%")
                                    if is_guided:
                                        if sge['max_yaw']: clines.append(f"        最大转向角: {sge['max_yaw']}°")
                                        drop_parts = []
                                        for ship_cls, col in [("航母", "drop_dist_aircarrier"), ("战列舰", "drop_dist_battleship"),
                                                              ("巡洋舰", "drop_dist_cruiser"), ("驱逐舰", "drop_dist_destroyer"),
                                                              ("潜艇", "drop_dist_submarine"), ("默认", "drop_dist_default")]:
                                            val = sge[col]
                                            if val is not None:
                                                drop_parts.append(f"{ship_cls}: {val} m")
                                        if drop_parts:
                                            clines.append(f"        放弃追踪距离: {' | '.join(drop_parts)}")
                    # 飞机携带的消耗品（从 ability_slot_0~4 读取）
                    for si in range(5):
                        slot_val = pid.get(f'ability_slot_{si}')
                        if not slot_val:
                            continue
                        parts = slot_val.split('|', 1)
                        aid = parts[0]
                        variant = parts[1] if len(parts) > 1 else ""
                        aname = self.resolve_name("consumable", aid)
                        clines.append(f"      ── 消耗品: {aname} ──")
                        if variant:
                            cfg = conn.execute(
                                "SELECT consumable_type, extra_json FROM consumable_configs "
                                "WHERE version_code=? AND consumable_id=? AND config_key=?",
                                (vc, aid, variant)).fetchone()
                            if cfg:
                                try:
                                    cd = json.loads(cfg['extra_json'] or '{}')
                                except Exception:
                                    cd = {}
                                ct = cfg['consumable_type'] or cd.get('consumableType', '')
                                num = cd.get('numConsumables')
                                prep = cd.get('preparationTime', 0)
                                cd_time = cd.get('reloadTime', 0)
                                wt = cd.get('workTime', 0)
                                auto = cd.get('isAutoConsumable', False)
                                clines.append(f"        类型: {ct}")
                                if num is not None:
                                    clines.append(f"        数量: {'无限' if num == -1 else num}")
                                if auto:
                                    clines.append(f"        自动使用: 是")
                                if prep:
                                    clines.append(f"        准备时间: {prep}s")
                                if cd_time:
                                    clines.append(f"        冷却时间: {cd_time}s")
                                if wt:
                                    clines.append(f"        持续时间: {wt}s")
                                clines.append(f"        消耗品效果:")
                                if ct == "crashCrew":
                                    clines.append(f"          扑灭起火、清除进水、并修复受损配件。")
                                elif ct == "healForsage":
                                    bc = cd.get('boostCoeff', 0)
                                    if bc:
                                        clines.append(f"          加速倍率: {bc}倍")
                                elif ct == "callFighters":
                                    fn = cd.get('fightersName', '')
                                    if fn:
                                        fdisp = self.resolve_name('plane', fn) or fn
                                        clines.append(f"          战斗机名称: {fdisp}")
                                    fn2 = cd.get('fightersNum', 0)
                                    is_inter = cd.get('isInterceptor', False)
                                    clines.append(f"          数量: {fn2} | 截击机: {'是' if is_inter else '否'}")
                                    dog = cd.get('dogFightTime', 0)
                                    fly = cd.get('flyAwayTime', 0)
                                    if dog or fly:
                                        clines.append(f"          狗斗: {dog}s | 离开: {fly}s")
                                    rk = cd.get('distanceToKill', 0)
                                    if rk:
                                        clines.append(f"          巡逻半径: {rk/10:.2f}km")
                                elif ct == "regenerateHealth":
                                    rr = cd.get('regenerationRate', 0)
                                    if rr:
                                        clines.append(f"          每秒回复血量: {rr*100:.0f}%")
                                    delay = cd.get('regenerationDelay', 0)
                                    if delay:
                                        clines.append(f"          回复延迟: {delay}s")
                config_contents[cg_label] = clines
            sub_contents[label] = {"config_labels": config_labels, "config_contents": config_contents}

        self._aircraft_sub_info = {"舰载机": {"sub_labels": sub_labels, "sub_contents": sub_contents}}
        return self.make_section("舰载机", [])
    def _build_air_support(self, conn, vc, ship_id, letter, result):
        lines = []
        TYPE_LABEL = {"spy": "情报侦察机", "smoke": "烟幕释放机", "scout": "伴航校射侦察机"}
        by_type: dict[str, list] = {}
        for s in conn.execute(
            "SELECT * FROM ship_module_air_support WHERE version_code=? AND ship_id=? AND config_group LIKE ?",
            (vc, ship_id, f"{letter}%")).fetchall():
            st = s['support_type'] or "other"
            by_type.setdefault(st, []).append(dict(s))
        for st in ("spy", "smoke", "scout", "damage", "other"):
            group = by_type.get(st)
            if not group:
                continue
            if st == "damage":
                arm = group[0].get('armament_name') or ""
                if not arm:
                    pi = conn.execute(
                        "SELECT bomb_name FROM plane_basic_info WHERE version_code=? AND plane_id=?",
                        (vc, self.resolve_plane_id(group[0]['plane_name']))).fetchone()
                    if pi and pi[0]:
                        arm = pi[0]
                if arm:
                    pbi = conn.execute(
                        "SELECT species, ammo_type FROM projectile_basic_info WHERE version_code=? AND projectile_id=?",
                        (vc, arm)).fetchone()
                    if pbi:
                        sp = pbi['species'] or ""
                        at = pbi['ammo_type'] or ""
                        if sp == "DepthCharge":
                            label = "深水炸弹空袭"
                        elif sp in ("bomb", "Bomb"):
                            if at == "AP":
                                label = "穿甲炸弹空袭"
                            elif at == "HE":
                                label = "高爆炸弹空袭"
                            elif at == "SAP":
                                label = "半穿甲炸弹空袭"
                            else:
                                label = "高爆炸弹空袭"
                        elif sp in ("rocket", "Rocket"):
                            if at == "AP":
                                label = "穿甲火箭空袭"
                            elif at == "HE":
                                label = "高爆火箭空袭"
                            else:
                                label = "火箭空袭"
                        else:
                            label = f"未知空袭({sp})"
                    else:
                        label = "未知空袭"
                else:
                    label = "未知空袭"
            else:
                label = TYPE_LABEL.get(st, st)
            lines.append(f"  [{label}]")
            for s in group:
                arm = s['armament_name'] or ""
                sname = self.resolve_plane(s['plane_name']) or s['plane_name']
                lines.append(f"    飞机型号: {sname}")
                if s['charges'] is not None: lines.append(f"      最大充能次数: {s['charges']}")
                if s['reload_time']: lines.append(f"      装填时间: {s['reload_time']}s")
                if s['work_time']: lines.append(f"      持续时间: {s['work_time']}s")
                mr = s['max_range']
                mir = s.get('min_range')
                def _fmt_range(v):
                    if v is None: return None
                    if v == float('inf'): return "无限"
                    return f"{v/1000:.2f} km"
                rtxt = _fmt_range(mr)
                if rtxt: lines.append(f"      最大距离: {rtxt}")
                rtxt2 = _fmt_range(mir)
                if rtxt2: lines.append(f"      最小距离: {rtxt2}")
                pi = conn.execute(
                    "SELECT * FROM plane_basic_info WHERE version_code=? AND plane_id=?",
                    (vc, self.resolve_plane_id(s['plane_name']))).fetchone()
                if pi:
                    pid = dict(pi)
                    # 支援飞机速度存在 speed_move_with_bomb 中
                    smwb = pid.get('speed_move_with_bomb')
                    if smwb:
                        max_mul = pid.get('speed_max_mult')
                        min_mul = pid.get('speed_min_mult')
                        lines.append(f"      巡航速度: {smwb} kts")
                        if max_mul: lines.append(f"          最大速度: {smwb * max_mul:.2f} kts")
                        if min_mul: lines.append(f"          最小速度: {smwb * min_mul:.2f} kts")
                    else:
                        if pid.get('max_speed'): lines.append(f"      航速: {pid['max_speed']} kts")
                        if pid.get('cruising_speed'): lines.append(f"      巡航速度: {pid['cruising_speed']} kts")
                    if pid.get('hp'): lines.append(f"      单架飞机血量: {pid['hp']:.0f}")
                    if pid.get('flight_height'): lines.append(f"      飞行高度: {pid['flight_height']}")
                    if pid.get('attacker_size'): lines.append(f"      攻击编组数量: {pid['attacker_size']}")
                    if pid.get('visibility_factor') is not None: lines.append(f"      被侦测距离: {pid['visibility_factor']} km")
                    # 如果 armament_name 为空，尝试从 plane_basic_info.bomb_name 获取弹药
                    if not arm and pid.get('bomb_name'):
                        arm = pid['bomb_name']
                    if arm and pid.get('attack_count'): lines.append(f"      载弹量: {pid['attack_count']}")
                if arm:
                    pbi = conn.execute(
                        "SELECT species, ammo_type FROM projectile_basic_info WHERE version_code=? AND projectile_id=?",
                        (vc, arm)).fetchone()
                    if pbi:
                        species = pbi['species'] or ""
                        atype = pbi['ammo_type'] or ""
                        lines.append(f"      ── 弹药: {species} ({atype}) ──")
                        _ac = "alpha_damage, bullet_krupp, alpha_piercing_he, alpha_piercing_cs, bullet_speed, explosion_radius, burn_prob, bullet_diameter, bullet_air_drag, bullet_always_ricochet_at, bullet_ricochet_at, bullet_detonator, bullet_detonator_threshold, bullet_cap_normalize_max"
                        _bc = f"damage, skips_json, max_skip_angle, {_ac}"
                        for tbl, cols in [("projectile_bullet_ext", _ac),
                                           ("projectile_bomb_ext", _bc),
                                           ("projectile_rocket_ext", f"damage, {_ac}"),
                                           ("projectile_depth_charge_ext", "damage, dc_speed, dc_timer, dc_max_depth, depth_splash_size")]:
                            ext = conn.execute(f"SELECT {cols} FROM {tbl} WHERE version_code=? AND projectile_id=?", (vc, arm)).fetchone()
                            if ext:
                                if tbl == "projectile_depth_charge_ext":
                                    if ext['damage']: lines.append(f"        标伤: {ext['damage']:.0f}")
                                    if ext['dc_speed']: lines.append(f"        下沉速度: {ext['dc_speed']:.2f} m/s")
                                    if ext['dc_timer']: lines.append(f"        引信定时: {ext['dc_timer']:.2f}s")
                                    if ext['dc_max_depth']: lines.append(f"        最大深度: {ext['dc_max_depth']:.0f} m")
                                    if ext['depth_splash_size']: lines.append(f"        溅射范围: {ext['depth_splash_size']:.2f} m")
                                else:
                                    if ext['alpha_damage']: lines.append(f"        标伤: {ext['alpha_damage']:.0f}")
                                    self._append_ammo_pen(lines, ext, atype)
                                    if ext['bullet_speed']: lines.append(f"        弹速: {ext['bullet_speed']:.0f} m/s")
                                    if ext['explosion_radius']: lines.append(f"        爆炸半径: {ext['explosion_radius']:.2f} m")
                                    if ext['burn_prob'] is not None: lines.append(f"        起火概率: {ext['burn_prob']*100:.2f}%")
                                    self._append_ammo_extra(lines, ext, atype)
                                break
                        # 跳弹数据（Bomb ext 中）
                        if ext and tbl == "projectile_bomb_ext":
                            self._append_skip_data(lines, ext)
                        # 火箭弹额外读取扫射序列
                        if species == "Rocket":
                            asq = conn.execute(
                                "SELECT attack_sequence_durations FROM projectile_rocket_ext WHERE version_code=? AND projectile_id=?",
                                (vc, arm)).fetchone()
                            if asq and asq['attack_sequence_durations']:
                                self._append_strafe_time(lines, asq['attack_sequence_durations'])
                        else:
                            te = conn.execute(
                                "SELECT alpha_damage, damage, torpedo_speed, torpedo_max_dist, torpedo_visibility, torpedo_arming_time, flood_generation, is_deep_water, deep_water_ignore_classes "
                                "FROM projectile_torpedo_ext WHERE version_code=? AND projectile_id=?",
                                (vc, arm)).fetchone()
                            if te:
                                sge = conn.execute("SELECT max_yaw FROM projectile_torpedo_sub_guidance_ext WHERE version_code=? AND projectile_id=?", (vc, arm)).fetchone()
                                is_guided = sge is not None
                                is_deep = te['is_deep_water']
                                if is_guided: lines.append(f"        类型: 声呐导向鱼雷")
                                elif is_deep: lines.append(f"        类型: 深水鱼雷")
                                ad = te['alpha_damage'] or 0
                                if ad: lines.append(f"        标伤: {ad * 0.33:.0f}")
                                if te['torpedo_speed']: lines.append(f"        航速: {te['torpedo_speed']:.0f} kts")
                                if te['torpedo_max_dist'] is not None: lines.append(f"        最大射程: {(te['torpedo_max_dist'] * 30) / 1000:.2f} km")
                                fg = te['flood_generation'] or 0
                                if fg: lines.append(f"        基础漏水率: {fg * 100:.0f}%")
        if lines:
            result[letter] = lines

    def _build_sub_section_info(self, conn, vc, ship_id, sections):
        """构建子分类映射：模块类型(船体/主炮) → {A/B/C 配置 → 内容}"""
        from collections import defaultdict
        # 先收集每封信的 module_id 列表
        letter_modules: dict[str, list[str]] = defaultdict(list)
        for r in conn.execute(
            "SELECT DISTINCT config_group, module_id FROM ship_module_relations "
            "WHERE version_code=? AND ship_id=? AND config_group NOT LIKE '%special%'",
            (vc, ship_id)).fetchall():
            cg = r["config_group"]
            letter = self._config_group_letter(cg)
            if letter not in letter_modules:
                letter_modules[letter] = []
        letters = sorted(letter_modules.keys())
        if len(letters) <= 1:
            return {}

        # 为每个 section label 提取该 section 下按 letter 拆分的内容
        sub_info: dict[str, dict] = {}
        for section in sections:
            label = section.get("label", "")
            # 检查该 section 是否为模块型（在 _append_modules 中添加的带 letter 分隔的 section）
            items = section.get("items", [])
            all_text = []
            for item in sorted(items, key=lambda x: x.get("order", 0)):
                n = item.get("name", "")
                v = item.get("value", "")
                all_text.append(v or n or "")
            full_text = "\n".join(all_text)
            # 按 letter 分割内容（查找 ──── X 配置 ──── 标记）
            letter_contents: dict[str, list[str]] = {}
            current_letter = None
            for line in full_text.split("\n"):
                m_letter = None
                for lt in letters:
                    if f"──── {lt} 配置 ────" in line:
                        m_letter = lt
                        break
                if m_letter is not None:
                    current_letter = m_letter
                    letter_contents.setdefault(current_letter, [])
                elif current_letter is not None:
                    letter_contents.setdefault(current_letter, []).append(line)
            if letter_contents and len(letter_contents) > 1:
                sub_labels = sorted(letter_contents.keys())
                sub_info[label] = {
                    "sub_labels": [f"{l} 配置" for l in sub_labels],
                    "sub_contents": {f"{l} 配置": letter_contents[l] for l in sub_labels},
                }
        return sub_info
