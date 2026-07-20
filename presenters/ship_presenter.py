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
            self.make_item("舰船名称", ship_name, 0),
            self.make_item("编号", basic['ship_index'] or ship_id.split('_')[0], 1),
            self.make_item("舰船 ID", str(basic['ship_id_num'] or ""), 2),
        ]
        for k, label, etype in [("shiptype", "舰种", "ship_class"), ("tier", "等级", ""), ("group_status_key", "状态", "ship_group")]:
            val = basic[k]
            if val is not None and val != "":
                resolved = self.resolve_enum(etype, val) if etype else str(val)
                items.append(self.make_item(label, resolved, len(items)))

        # parent_ship / origin_ship — 提取编号前缀后再映射中文名
        for k, label in [("parent_ship_id", "原型舰船"), ("origin_ship_id", "原型舰船")]:
            if basic[k]:
                raw = basic[k].split("_")[0]  # PASA538_Hornet → PASA538
                pname = self.resolve_name('ship', raw)
                items.append(self.make_item(label, pname, len(items)))
        sections.append(self.make_section("基础属性", items, icon="📋"))

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

        # ── 6. 顶部配置栏数据 ───────────────────────────
        config_bar = self._build_config_bar(conn, vc, ship_id, basic)

        return {
            "title": ship_name,
            "subtitle": f"ID: {ship_id}",
            "sections": sections,
            "extra": {"sub_sections": sub_info} if sub_info else {},
            "config_bar": config_bar,
        }

    # ── 辅助 ───────────────────────────────────────────────

    @staticmethod
    def _config_group_letter(config_group: str) -> str:
        """从 config_group (如 'AB1', 'A') 提取首字母"""
        return config_group[0] if config_group else "?"

    def _append_strafe_time(self, items: list, seq_json: str, o: int) -> int:
        """解析 attack_sequence_durations JSON 数组并显示扫射时序"""
        try:
            import json
            seq = json.loads(seq_json) if isinstance(seq_json, str) else seq_json
            if not isinstance(seq, (list, tuple)) or len(seq) < 2:
                return o
            total = sum(seq)
            items.append(self.make_item("扫射时间", f"{total:.1f}", o, unit="s")); o += 1
        except Exception:
            pass
        return o

    def _append_skip_data(self, items: list, row, o: int) -> int:
        """显示跳弹数据：弹跳次数、最大触发角度"""
        import json
        try:
            skips_raw = row['skips_json']
            if not skips_raw:
                return o
            skips = json.loads(skips_raw) if isinstance(skips_raw, str) else skips_raw
            if isinstance(skips, (list, tuple)):
                skip_count = len(skips)
                items.append(self.make_item("弹跳次数", f"{skip_count} 次", o)); o += 1
                items.append(self.make_item("总共落点段数", f"{skip_count + 1} 段", o)); o += 1
            if row['max_skip_angle']:
                items.append(self.make_item("最大弹跳触发角度", f"{row['max_skip_angle']:.0f}", o, unit="°")); o += 1
        except Exception:
            pass
        return o

    def _append_ammo_pen(self, items: list, row, ammo_type: str, o: int) -> int:
        """根据弹药类型显示穿深或硬度（row 为 sqlite3.Row，仅支持 [] 访问）"""
        try:
            if ammo_type == "HE":
                v = row['alpha_piercing_he']
                if v: items.append(self.make_item("穿深", f"{v:.1f}", o, unit="mm")); o += 1
            elif ammo_type == "CS":
                v = row['alpha_piercing_cs']
                if v: items.append(self.make_item("穿深", f"{v:.1f}", o, unit="mm")); o += 1
            elif ammo_type == "AP":
                v = row['bullet_krupp']
                if v: items.append(self.make_item("硬度", f"{v:.0f}", o)); o += 1
            else:
                v = row['bullet_krupp']
                if v: items.append(self.make_item("穿深", f"{v:.0f}", o)); o += 1
        except (KeyError, IndexError, TypeError):
            pass
        return o

    def _append_ammo_extra(self, items: list, row, ammo_type: str, o: int) -> int:
        """AP/CS 专属属性：阻力系数、口径、跳弹角、引信等"""
        if ammo_type not in ("AP", "CS"):
            return o
        try:
            if row['bullet_air_drag']:
                items.append(self.make_item("阻力系数", str(row['bullet_air_drag']), o)); o += 1
            if row['bullet_diameter']:
                items.append(self.make_item("口径", f"{row['bullet_diameter']*1000:.2f}", o, unit="mm")); o += 1
            if row['bullet_always_ricochet_at']:
                items.append(self.make_item("强制跳弹角", f"{row['bullet_always_ricochet_at']:.0f}", o, unit="°")); o += 1
            if row['bullet_ricochet_at']:
                items.append(self.make_item("概率跳弹角", f"{row['bullet_ricochet_at']:.0f}", o, unit="°")); o += 1
            if row['bullet_cap_normalize_max']:
                items.append(self.make_item("弹头转正角", f"{row['bullet_cap_normalize_max']:.0f}", o, unit="°")); o += 1
            if ammo_type == "AP":
                if row['bullet_detonator']:
                    items.append(self.make_item("引信长度", f"{row['bullet_detonator']:.0f}", o, unit="s")); o += 1
                if row['bullet_detonator_threshold']:
                    items.append(self.make_item("引信触发阈值", f"{row['bullet_detonator_threshold']:.0f}", o, unit="mm")); o += 1
        except (KeyError, IndexError, TypeError):
            pass
        return o

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
        # 收集原始消耗品数据供 UI 构建按钮
        raw_slots: list[dict] = []
        for s in slots:
            raw_slots.append({
                "slot_index": s['slot_index'],
                "item_index": s['item_index'],
                "consumable_id": s['consumable_id'],
                "config_key": s['config_key'],
                "display_name": self.resolve_name_by_id(
                    s['display_name_id'], 'consumable', s['consumable_id']
                ) or s['consumable_id'] or "",
            })
        sections.append({
            "label": "消耗品数据", "items": items, "icon": "💊",
            "raw_consumables": raw_slots,
        })

    # ── 战斗指令 ───────────────────────────────────────────

    def _append_rage_mode(self, conn, vc, ship_id, sections):
        rage = conn.execute(
            "SELECT * FROM ship_rage_mode WHERE version_code=? AND ship_id=?", (vc, ship_id)).fetchone()
        if not rage:
            return
        items = []
        o = 0
        dname = self.resolve_name_by_id(rage['display_name_id'], 'rage_mode', rage['rage_mode_name']) or "战斗指令"
        # 跳过 === dname === 重复标题
        boost_dur = float(rage['boost_duration'] or 0)
        items.append(self.make_item("持续时间", "即时" if boost_dur == 0 else f"{boost_dur}s", o)); o += 1
        max_ac = rage['max_activation_count']
        if max_ac != '-1':
            items.append(self.make_item("最大激活次数", f'{max_ac} 次', o)); o += 1
        items.append(self.make_item("自动激活", '是' if rage['is_auto_usage'] else '否', o)); o += 1
        items.append(self.make_item("常驻生效", '是' if rage['is_modifier_works_always'] else '否', o)); o += 1

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
                    act = tdata.get("Activator", {})
                    atype = act.get("type", "")

                    # 提取所有动作数据
                    actions_found = {k: v for k, v in tdata.items() if k.startswith("Action") and isinstance(v, dict)}

                    if tkey == "GameLogicTriggerProgress" and atype == "RibbonActivator":
                        # 进度积累专用格式：每获得N个xx/yy勋带时获得M进度
                        ribbons = act.get("subRibbons", [])
                        rnames = [NM.RIBBON_MAP.get(str(rid), str(rid)) for rid in ribbons] if ribbons else []
                        req = act.get("requiredCount", 1)
                        progress_val = ""
                        for ak, aln in actions_found.items():
                            if aln.get("type") == "RageModeProgressAction":
                                progress_val = str(aln.get("progress", ""))
                        ribbon_str = "/".join(rnames) if rnames else ""
                        if ribbon_str:
                            display = f"每获得{req}个{ribbon_str}勋带时"
                            if progress_val:
                                display += f"获得{progress_val}进度"
                            items.append(self.make_item(trigger_label, display, o)); o += 1
                        continue

                    # 构建激活条件描述（其他触发类型）
                    cond_parts = []
                    if atype == "RageModeStateChangedActivator":
                        st = act.get("stateName", "")
                        if st:
                            cond_parts.append(f"状态: {st}")
                    elif atype == "RibbonActivator":
                        ribbons = act.get("subRibbons", [])
                        if ribbons and isinstance(ribbons, list):
                            names = [NM.RIBBON_MAP.get(str(rid), str(rid)) for rid in ribbons]
                            cond_parts.append(f"勋带: {', '.join(names)}")
                    req = act.get("requiredCount", 0)
                    if req:
                        cond_parts.append(f"次数: {req}")
                    if act.get("separateTracking"):
                        cond_parts.append("独立追踪")

                    effect_parts = []
                    if actions_found:
                        for action_key, aln in actions_found.items():
                            atype2 = aln.get("type", "")
                            if atype2 in ("ReduceSquadronPreparationTimeAction",):
                                pn = aln.get("planeName") or aln.get("planeId", "")
                                pname = self.resolve_plane(pn) or pn if pn else ""
                                rt = aln.get("reduceTime", 0)
                                if pname and rt:
                                    effect_parts.append(f"{pname}整备时间: -{rt}s")
                                elif rt:
                                    effect_parts.append(f"-{rt}s 整备时间")
                            elif atype2 == "RageModeProgressAction":
                                pn = aln.get("progressName", "")
                                if pn:
                                    effect_parts.append(f"进度: {pn}")
                            else:
                                extra = {k: v for k, v in aln.items() if k != "type"}
                                for ek, ev in extra.items():
                                    label = NM.DETAIL_MAP.get(ek, ek)
                                    effect_parts.append(f"{label}: {ev}")

                    cond_str = ', '.join(cond_parts) if cond_parts else ""

                    if tkey == "GameLogicTriggerOnActivation":
                        effect_str = '; '.join(effect_parts) if effect_parts else ""
                        if effect_str:
                            items.append(self.make_item(trigger_label, effect_str, o)); o += 1
                    elif tkey == "GameLogicTriggerProgress":
                        # 进度积累：只显示条件
                        if cond_str:
                            items.append(self.make_item(trigger_label, cond_str, o)); o += 1
                    else:
                        effect_str = '; '.join(effect_parts) if effect_parts else ""
                        display = effect_str or cond_str
                        if display:
                            items.append(self.make_item(trigger_label, display, o)); o += 1

        # ── 加成效果 ──
        mods_raw = rage['modifiers_json']
        if mods_raw:
            try:
                mods = json.loads(mods_raw)
                if isinstance(mods, dict) and mods:
                    for mk, mv in sorted(mods.items()):
                        label = Mapping.MODIFIER_MAP.get(mk, mk)
                        if isinstance(mv, dict):
                            for species_key, factor in mv.items():
                                cn = NM.SHIP_CLASS_MAP.get(species_key, species_key)
                                items.append(self.make_item(f"{label}({cn})", f"{(factor - 1) * 100:+.0f}%", o)); o += 1
                        elif mk == "healthRegen":
                            items.append(self.make_item(label, f"每秒回复 {mv:.0f} HP", o)); o += 1
                        elif isinstance(mv, (float, int)):
                            if mv > 10.0:
                                items.append(self.make_item(label, f"+{mv:.0f}", o)); o += 1
                            else:
                                items.append(self.make_item(label, f"{(mv - 1) * 100:+.0f}%", o)); o += 1
                        else:
                            items.append(self.make_item(label, f"{mv}", o)); o += 1
            except (json.JSONDecodeError, TypeError):
                pass

        sections.append(self.make_section("战斗指令", items))

        # 附加原始数据供 UI 按钮使用
        raw_rm_name = rage["rage_mode_name"] or ""
        # 从 IDS_DOCK_RAGE_MODE_TITLE_xxx 中提取原始 xxx
        if raw_rm_name.startswith("IDS_DOCK_RAGE_MODE_TITLE_"):
            raw_rm_name = raw_rm_name[len("IDS_DOCK_RAGE_MODE_TITLE_"):].lower()
        sections[-1]["raw_rage_mode"] = {
            "rage_mode_name": raw_rm_name,
            "display_name": dname,
        }

    # ── 模块 ───────────────────────────────────────────────

    def _append_modules(self, conn, vc, ship_id, sections):
        # 获取所有配置组前缀字母
        letters = set()
        for tbl in ["ship_module_hulls", "ship_module_artillery", "ship_module_secondary_artillery",
                      "ship_module_atba",
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
        hull_data, arty_data, atba_data, secondary_arty_data, torp_data = {}, {}, {}, {}, {}
        aa_data, dc_data, plane_data, asup_data = {}, {}, {}, {}

        for letter in letters:
            self._build_hull(conn, vc, ship_id, letter, hull_data)
            self._build_artillery(conn, vc, ship_id, letter, arty_data)
            self._build_atba(conn, vc, ship_id, letter, atba_data)
            self._build_secondary_artillery(conn, vc, ship_id, letter, secondary_arty_data)
            self._build_torpedoes(conn, vc, ship_id, letter, torp_data)
            self._build_aa(conn, vc, ship_id, letter, aa_data)
            self._build_depth_charge(conn, vc, ship_id, letter, dc_data)
            self._build_air_support(conn, vc, ship_id, letter, asup_data)

        for label, data in [("船体", hull_data), ("主炮", arty_data), ("副炮", atba_data),
                             ("次级主炮", secondary_arty_data),
                             ("鱼雷", torp_data), ("防空", aa_data), ("深水炸弹", dc_data)]:
            if data:
                all_items: list[dict] = []
                all_ammo: list[dict] = []
                for letter in letters:
                    entry = data.get(letter)
                    if not entry:
                        continue
                    # 支持 (items, raw_ammo_types) 元组和纯 items 列表两种格式
                    if isinstance(entry, tuple):
                        letter_items, letter_ammo = entry
                    else:
                        letter_items, letter_ammo = entry, []
                    if letter_items:
                        if len(letters) > 1:
                            all_items.append(self.make_item(f"── {letter} 配置 ──", "", len(all_items), row_type="header"))
                        all_items.extend(letter_items)
                        if letter_ammo:
                            all_ammo.extend(letter_ammo)
                section = self.make_section(label, all_items)
                if all_ammo:
                    section["raw_ammo_types"] = all_ammo
                sections.append(section)
        # 舰载机独立处理：一个 section + 次级菜单
        plane_section = self._build_aircraft_panel(conn, vc, ship_id, letters, sections)
        if plane_section:
            sections.append(plane_section)
        # 空袭
        if asup_data:
            all_items: list[dict] = []
            all_ammo: list[dict] = []
            for letter in letters:
                entry = asup_data.get(letter, {})
                if not entry:
                    continue
                letter_items = entry.get("items", [])
                letter_ammo = entry.get("raw_ammo_types", [])
                if letter_items:
                    if len(letters) > 1:
                        all_items.append(self.make_item(f"── {letter} 配置 ──", "", len(all_items), row_type="header"))
                    all_items.extend(letter_items)
                    if letter_ammo:
                        all_ammo.extend(letter_ammo)
            if all_items:
                section = self.make_section("支援", all_items)
                if all_ammo:
                    section["raw_ammo_types"] = all_ammo
                sections.append(section)

    # ── 模块构建子方法 ─────────────────────────────────────

    def _build_hull(self, conn, vc, ship_id, letter, result):
        items = []
        o = 0
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
            for col, label, unit in [
                ("health", "基础血量", ""),
                ("max_speed", "最大航速", "kts"),
                ("turning_radius", "转弯半径", "m"),
                ("rudder_time", "转舵时间", "s"),
                ("engine_power", "引擎马力", "HP"),
            ]:
                val = h[col]
                if val is not None:
                    items.append(self.make_item(label, f"{val:.0f}" if col in ("health","engine_power") else f"{val:.2f}", o, unit=unit))
                    o += 1

            # 隐蔽（带最小隐蔽详情）
            for col, label in [("conceal_sea", "水面隐蔽"), ("conceal_air", "空中隐蔽")]:
                val = h[col]
                if val is not None:
                    min_val = h[col] * conceal_coeff
                    min_label = "最小水面隐蔽" if col == "conceal_sea" else "最小空中隐蔽"
                    items.append(self.make_item(
                        label, f"{val:.2f}", o, unit="km",
                        details=[{"name": min_label, "value": f"{min_val:.2f}", "unit": "km"}]
                    ))
                    o += 1

            # 是否有核心区
            if h['has_citadel'] is not None:
                items.append(self.make_item("是否有核心区", "是" if h['has_citadel'] else "否", o)); o += 1

            # 潜艇扩展数据
            ext = conn.execute(
                "SELECT * FROM ship_module_hulls_ext WHERE version_code=? AND ship_id=? AND config_group=? AND module_key=?",
                (vc, ship_id, h['config_group'], h['module_key'])).fetchone()
            if ext:
                for col, label, unit in [
                    ("battery_capacity", "电池容量", ""),
                    ("battery_regen", "电力恢复", "/s"),
                    ("hydrophone_radius", "水听器工作半径", "km"),
                    ("hydrophone_update_freq", "水听器更新周期", "s"),
                    ("buoyancy_rudder_time", "水平舵转舵时间", "s"),
                    ("max_buoyancy_speed", "最大上浮/下潜速度", "kts"),
                ]:
                    v = ext[col]
                    if v is not None:
                        items.append(self.make_item(label, f"{v:.2f}" if isinstance(v, float) else str(v), o, unit=unit))
                        o += 1

                # 深度状态
                for ds in conn.execute(
                    "SELECT * FROM ship_sub_depth_states WHERE version_code=? AND ship_id=? AND config_group=? AND module_key=?",
                    (vc, ship_id, h['config_group'], h['module_key'])).fetchall():
                    cn_name = NM.DEPTH_MAP.get(ds['state_name'], ds['state_name'])
                    depth_val = f"航速×{ds['underwater_max_speed']}"
                    if ds['visibility_factor'] is not None:
                        depth_val += f", 隐蔽×{ds['visibility_factor']}"
                    items.append(self.make_item(f"深度-{cn_name}", depth_val, o)); o += 1

        if items:
            result[letter] = items

    def _build_artillery(self, conn, vc, ship_id, letter, result):
        ammo_map = self.get_name_map("ammo")
        rows = conn.execute(
            "SELECT * FROM ship_module_artillery WHERE version_code=? AND ship_id=? AND config_group LIKE ? ORDER BY module_key",
            (vc, ship_id, f"{letter}%")).fetchall()
        if not rows:
            return
        groups = self._group_weapon_rows(conn, vc, ship_id, rows, 'artillery', ammo_map)
        items, raw_ammo_types = self._render_weapon_groups(conn, vc, groups, ammo_map)
        if items:
            result[letter] = (items, raw_ammo_types)

    def _group_weapon_rows(self, conn, vc, ship_id, rows, slot_type, ammo_map):
        """按炮塔属性分组同一模块下的相同武器"""
        groups: list[dict] = []
        for g_row in rows:
            g = dict(g_row)  # sqlite3.Row → dict
            # 取该武器可用的弹药 ID 列表
            ammo_ids = sorted(
                r["ammo_id"] for r in conn.execute(
                    "SELECT DISTINCT ammo_id FROM ship_weapon_projectiles "
                    "WHERE version_code=? AND ship_id=? AND module_id=? AND slot_type=?",
                    (vc, ship_id, g['module_key'], slot_type)).fetchall()
            )
            # 取特殊机制数据（如果有）
            drum = None
            ext = conn.execute(
                "SELECT * FROM ship_module_artillery_ext WHERE version_code=? AND ship_id=? AND config_group=? AND module_key=?",
                (vc, ship_id, g['config_group'], g['module_key'])).fetchone()
            if ext and ext['special_mode_name']:
                drum = dict(ext)

            key = (
                g['module_key'],
                g['num_barrels'],
                g['reload_time'],
                g['max_range'],
                g['sigma'],
                g['ideal_radius'], g['min_radius'], g['ideal_distance'],
                g['radius_zero'], g['radius_delim'], g['radius_max'], g['delim'],
                g.get('rotation_speed_h'), g.get('rotation_speed_v'),
                g.get('caliber'),
                tuple(ammo_ids),
                json.dumps(dict(drum)) if drum else None,
            )
            # 查找已有相同分组
            found = None
            for grp in groups:
                if grp["key"] == key:
                    found = grp
                    break
            if found:
                found["count"] += g['count']
            else:
                groups.append({"key": key, "row": dict(g), "count": g['count'], "drum": drum, "ammo_ids": ammo_ids})
        return groups

    def _render_weapon_groups(self, conn, vc, groups, ammo_map):
        """将分组后的武器数据渲染为 items。
        相同火炮名称的组会自动合并属性（不同值用 / 分隔，相同值只显示一次）。"""
        items = []
        raw_ammo_types: list[dict] = []
        # 按火炮名称分组
        name_groups: dict[str, list[dict]] = {}
        for grp in groups:
            gname = self.resolve_name('gun', grp["row"]['module_key']) or grp["row"]['module_key']
            name_groups.setdefault(gname, []).append(grp)

        o = 0
        for gname, grp_list in name_groups.items():
            if len(grp_list) == 1:
                items, o, ammo = self._render_single_weapon_group(conn, vc, grp_list[0], ammo_map, items, o)
                raw_ammo_types.extend(ammo)
            else:
                items, o, ammo = self._render_merged_weapon_groups(conn, vc, grp_list, ammo_map, items, o)
                raw_ammo_types.extend(ammo)
        # 弹药去重：同种弹药只保留一个条目
        seen_ids: set[str] = set()
        deduped: list[dict] = []
        for a in raw_ammo_types:
            aid = a.get("ammo_id", "")
            if aid and aid not in seen_ids:
                seen_ids.add(aid)
                deduped.append(a)
        return items, deduped

    def _render_single_weapon_group(self, conn, vc, grp, ammo_map, items, o):
        """渲染单个武器组"""
        g = grp["row"]
        total_count = grp["count"]
        drum = grp["drum"]
        ammo_ids = grp["ammo_ids"]
        gname = self.resolve_name('gun', g['module_key']) or g['module_key']
        items.append(self.make_item("火炮名称", f"{gname} x{total_count}", o)); o += 1
        if g['num_barrels']: items.append(self.make_item("联装数", f"{g['num_barrels']:.0f}", o)); o += 1
        if g['reload_time']: items.append(self.make_item("装填时间", str(g['reload_time']), o, unit="s")); o += 1
        items, o = self._append_weapon_common(conn, vc, g, items, o)
        raw_ammo = self._collect_ammo_types(conn, vc, ammo_ids, ammo_map)
        for a in raw_ammo:
            items.append(self.make_item("弹药", a["name"], o)); o += 1
        items, o = self._append_drum(drum, items, o)
        return items, o, raw_ammo

    def _render_merged_weapon_groups(self, conn, vc, grp_list, ammo_map, items, o):
        """合并多个同名武器组的属性显示"""
        all_vals: dict[str, list] = {}
        all_ammo_ids: set[str] = set()
        all_drums = []
        total_count = 0
        g0 = grp_list[0]["row"]

        for grp in grp_list:
            g = grp["row"]
            total_count += grp["count"]
            all_ammo_ids.update(grp["ammo_ids"])
            if grp["drum"]:
                all_drums.append(grp["drum"])
            for key in ('num_barrels', 'reload_time'):
                val = g.get(key)
                if val is not None:
                    all_vals.setdefault(key, []).append(val)

        gname = self.resolve_name('gun', g0['module_key']) or g0['module_key']
        items.append(self.make_item("火炮名称", f"{gname} x{total_count}", o)); o += 1

        barrel_vals = all_vals.get('num_barrels', [])
        if barrel_vals:
            display = f"{barrel_vals[0]:.0f}" if len(set(barrel_vals)) == 1 else " / ".join(f"{v:.0f}" for v in barrel_vals)
            items.append(self.make_item("联装数", display, o)); o += 1
        reload_vals = all_vals.get('reload_time', [])
        if reload_vals:
            display = f"{reload_vals[0]} s" if len(set(reload_vals)) == 1 else " / ".join(f"{v} s" for v in reload_vals)
            items.append(self.make_item("装填时间", display, o)); o += 1

        items, o = self._append_weapon_common(conn, vc, g0, items, o)
        raw_ammo = self._collect_ammo_types(conn, vc, sorted(all_ammo_ids), ammo_map)
        for a in raw_ammo:
            items.append(self.make_item("弹药", a["name"], o)); o += 1

        if all_drums:
            items, o = self._append_drum(all_drums[0], items, o)
        return items, o, raw_ammo

    def _append_weapon_common(self, conn, vc, g, items, o):
        """添加武器共有属性（散步/Sigma/回转/口径）"""
        if g['max_range']: items.append(self.make_item("最大射程", f"{g['max_range']:.2f}", o, unit="km")); o += 1
        ir, mr, id_dist = g['ideal_radius'], g['min_radius'], g['ideal_distance']
        if ir and mr and id_dist:
            slope = (ir - mr) / (id_dist / 1000) if id_dist else 0
            intercept = mr * 30
            items.append(self.make_item("横向散步公式", f"{slope:.2f}R + {intercept:.0f}", o)); o += 1
        if g['radius_zero'] is not None and g['radius_max'] is not None:
            r0, rdelim, rmax, delim = g['radius_zero'], g['radius_delim'], g['radius_max'], g['delim']
            pct = f"{delim*100:.0f}%" if delim else "?"
            items.append(self.make_item("纵向散步系数", f"{r0} ~ {rdelim}(R={pct}) ~ {rmax}", o)); o += 1
        if g['sigma']: items.append(self.make_item("弹着群系数(Sigma)", str(g['sigma']), o)); o += 1
        if g.get('rotation_speed_h'): items.append(self.make_item("水平回转速度", f"{g['rotation_speed_h']:.1f}", o, unit="°/s")); o += 1
        if g.get('rotation_speed_v'): items.append(self.make_item("垂直回转速度", f"{g['rotation_speed_v']:.1f}", o, unit="°/s")); o += 1
        if g.get('caliber'): items.append(self.make_item("口径", f"{g['caliber']*1000:.0f}", o, unit="mm")); o += 1
        return items, o

    def _collect_ammo_types(self, conn, vc, ammo_ids, ammo_map):
        """收集弹药类型信息（已去重），用于按钮 + 详情卡片"""
        seen_ids = set()
        result = []
        for aid in ammo_ids:
            if aid in seen_ids:
                continue
            seen_ids.add(aid)
            acn = ammo_map.get(aid.upper(), aid)
            p = conn.execute(
                "SELECT pb.species, pb.ammo_type, be.alpha_damage, be.bullet_krupp, "
                "be.alpha_piercing_he, be.alpha_piercing_cs, "
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
                species = p['species'] or ""
                detail_items = self._build_ammo_detail_items(p, at)
                result.append({
                    "ammo_id": aid, "name": acn,
                    "species": species, "ammo_type": at,
                    "detail_items": detail_items,
                })
            else:
                result.append({
                    "ammo_id": aid, "name": acn,
                    "species": "", "ammo_type": "", "detail_items": [],
                })
        return result

    def _build_ammo_detail_items(self, p, at):
        """构建弹药详情显示项"""
        detail_items = []
        di = 0
        if p['alpha_damage']: detail_items.append(self.make_item("标伤", f"{p['alpha_damage']:.0f}", di)); di += 1
        detail_items.append(self.make_item("弹种", p['ammo_type'] or '?', di)); di += 1
        if at == 'HE':
            if p['burn_prob'] is not None: detail_items.append(self.make_item("起火率", f"{p['burn_prob']*100:.2f}", di, unit="%")); di += 1
            if p['alpha_piercing_he']: detail_items.append(self.make_item("HE穿深", f"{p['alpha_piercing_he']:.1f}", di, unit="mm")); di += 1
        elif at == 'SAP':
            if p['alpha_piercing_cs']: detail_items.append(self.make_item("SAP穿深", f"{p['alpha_piercing_cs']:.1f}", di, unit="mm")); di += 1
            rc1 = p['bullet_ricochet_at']; rc2 = p['bullet_always_ricochet_at']
            if rc1 or rc2:
                detail_items.append(self.make_item("跳弹角度", f"{rc1:.1f}°/{rc2:.1f}°", di)); di += 1
        elif at == 'AP':
            if p['bullet_krupp']: detail_items.append(self.make_item("弹头硬度", f"{p['bullet_krupp']:.0f}", di)); di += 1
            if p['bullet_detonator'] is not None: detail_items.append(self.make_item("引信触发阈值", f"{p['bullet_detonator']:.0f}", di, unit="mm")); di += 1
            if p['bullet_detonator_threshold']: detail_items.append(self.make_item("引信长度", f"{p['bullet_detonator_threshold']:.2f}", di, unit="")); di += 1
            if p['bullet_cap_normalize_max']: detail_items.append(self.make_item("炮弹转正角", f"{p['bullet_cap_normalize_max']:.2f}", di, unit="°")); di += 1
            rc1 = p['bullet_ricochet_at']; rc2 = p['bullet_always_ricochet_at']
            if rc1 or rc2:
                detail_items.append(self.make_item("跳弹角度", f"{rc1:.0f}°/{rc2:.0f}°", di)); di += 1
        if p['explosion_radius']: detail_items.append(self.make_item("爆炸半径", f"{p['explosion_radius']:.2f}", di, unit="m")); di += 1
        if p['bullet_speed']: detail_items.append(self.make_item("弹速", f"{p['bullet_speed']:.0f}", di, unit="m/s")); di += 1
        if p['bullet_mass']: detail_items.append(self.make_item("弹重", f"{p['bullet_mass']:.2f}", di, unit="kg")); di += 1
        return detail_items

    def _append_drum(self, drum, items, o):
        """添加特殊机制（弹夹/弹鼓炮）"""
        if not drum:
            return items, o
        sc = drum['drum_shots_count']
        sd = drum['drum_shot_delay']
        frt = drum['drum_full_reload_time']
        is_chargeable = drum['drum_is_chargeable']
        is_switchable = drum['drum_is_switchable']
        if is_chargeable:
            items.append(self.make_item("特殊机制", "弹鼓炮", o, row_type="header")); o += 1
            items.append(self.make_item("连发数量", f"{sc:.0f}", o)); o += 1
            items.append(self.make_item("连发间隔", f"{sd}s", o)); o += 1
            cmode = drum['drum_charge_mode']
            cmin = drum['drum_charge_time_min']
            cmax = drum['drum_charge_time_max']
            if cmode == 1:
                items.append(self.make_item("第 1 轮装填时间", f"{cmin}s", o)); o += 1
                items.append(self.make_item(f"第 2 ~ {sc:.0f} 轮装填时间", f"{cmax}s", o)); o += 1
            elif cmode == 2:
                items.append(self.make_item(f"第 1 ~ {sc-1:.0f} 轮装填时间", f"{cmin}s", o)); o += 1
                items.append(self.make_item(f"第 {sc:.0f} 轮(末轮)装填时间", f"{cmax}s", o)); o += 1
        else:
            switch_prefix = "可切换" if is_switchable else "强制"
            items.append(self.make_item("特殊机制", f"{switch_prefix}连发射击-弹夹炮", o, row_type="header")); o += 1
            items.append(self.make_item("长装填时间", f"{frt}s", o)); o += 1
            items.append(self.make_item("连发间隔", f"{sd}s", o)); o += 1
            items.append(self.make_item("连发轮数", f"{sc:.0f}", o)); o += 1
        mods_raw = drum['drum_modifiers_json']
        if mods_raw and mods_raw != '{}':
            try:
                mods = json.loads(mods_raw)
                if isinstance(mods, dict) and mods:
                    for mk, mv in sorted(mods.items()):
                        label = Mapping.MODIFIER_MAP.get(mk, mk)
                        items.append(self.make_item(label, f"{(mv-1)*100:+.0f}%", o)); o += 1
            except (json.JSONDecodeError, TypeError):
                pass
        return items, o

    def _build_atba(self, conn, vc, ship_id, letter, result):
        ammo_map = self.get_name_map("ammo")
        rows = conn.execute(
            "SELECT * FROM ship_module_atba WHERE version_code=? AND ship_id=? AND config_group LIKE ? ORDER BY module_key",
            (vc, ship_id, f"{letter}%")).fetchall()
        if not rows:
            return
        groups = self._group_weapon_rows(conn, vc, ship_id, rows, 'atba', ammo_map)
        items, raw_ammo_types = self._render_weapon_groups(conn, vc, groups, ammo_map)
        if items:
            result[letter] = (items, raw_ammo_types)

    def _build_secondary_artillery(self, conn, vc, ship_id, letter, result):
        """从 ship_module_secondary_artillery 表构建第二主炮显示数据"""
        ammo_map = self.get_name_map("ammo")
        rows = conn.execute(
            "SELECT * FROM ship_module_secondary_artillery WHERE version_code=? AND ship_id=? AND config_group LIKE ? ORDER BY module_key",
            (vc, ship_id, f"{letter}%")).fetchall()
        if not rows:
            return
        groups = self._group_weapon_rows(conn, vc, ship_id, rows, 'secondary_artillery', ammo_map)
        items, raw_ammo_types = self._render_weapon_groups(conn, vc, groups, ammo_map)
        if items:
            result[letter] = (items, raw_ammo_types)

    def _build_torpedoes(self, conn, vc, ship_id, letter, result):
        items = []
        o = 0
        ammo_map = self.get_name_map("ammo")
        rows = conn.execute(
            "SELECT * FROM ship_module_torpedoes WHERE version_code=? AND ship_id=? AND config_group LIKE ? ORDER BY module_key",
            (vc, ship_id, f"{letter}%")).fetchall()
        if not rows:
            return
        # 分组
        groups: list[dict] = []
        for t in rows:
            ammo_ids = sorted(
                r["ammo_id"] for r in conn.execute(
                    "SELECT DISTINCT ammo_id FROM ship_weapon_projectiles "
                    "WHERE version_code=? AND ship_id=? AND module_id=? AND slot_type='torpedo'",
                    (vc, ship_id, t['module_key'])).fetchall()
            )
            key = (t['module_key'], t['reload_time'], tuple(ammo_ids))
            found = None
            for grp in groups:
                if grp["key"] == key:
                    found = grp
                    break
            if found:
                found["count"] += t['count']
            else:
                groups.append({"key": key, "row": dict(t), "count": t['count'], "ammo_ids": ammo_ids})
        # 渲染
        for grp in groups:
            t = grp["row"]
            total_count = grp["count"]
            ammo_ids = grp["ammo_ids"]
            tname = self.resolve_name('gun', t['module_key']) or t['module_key']
            items.append(self.make_item("鱼雷发射管", f"{tname} x{total_count}", o)); o += 1
            if t['reload_time']: items.append(self.make_item("装填时间", str(t['reload_time']), o, unit="s")); o += 1
            for aid in ammo_ids:
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
                    if is_guided:
                        dtype = "声呐导向鱼雷"
                    elif is_deep:
                        dtype = "深水鱼雷"
                    elif is_burn:
                        dtype = "热能鱼雷"
                    else:
                        dtype = "鱼雷"
                    items.append(self.make_item(f"── {aname} ({dtype}) ──", "", o, row_type="header")); o += 1
                    ad = p['alpha_damage'] or 0
                    if ad: items.append(self.make_item("标伤", f"{ad * 0.33:.0f}", o)); o += 1
                    if p['torpedo_speed']: items.append(self.make_item("航速", f"{p['torpedo_speed']:.0f}", o, unit="kts")); o += 1
                    dist = p['torpedo_max_dist']
                    if dist: items.append(self.make_item("射程", f"{dist * 0.03:.2f}", o, unit="km")); o += 1
                    if p['torpedo_visibility']: items.append(self.make_item("被发现距离", f"{p['torpedo_visibility']:.2f}", o, unit="km")); o += 1
                    if p['torpedo_arming_time']: items.append(self.make_item("鱼雷上浮时间", f"{p['torpedo_arming_time']:.2f}", o, unit="s")); o += 1
                    if p['flood_generation'] and p['uw_critical']:
                        items.append(self.make_item("基础漏水系数", f"{p['uw_critical']:.2f}", o)); o += 1
                    if is_burn and p['burn_prob']:
                        items.append(self.make_item("基础点火率", f"{p['burn_prob']*100:.0f}", o, unit="%")); o += 1
                    if sge:
                        if sge['search_radius']: items.append(self.make_item("搜索半径", f"{sge['search_radius']:.2f}", o, unit="km")); o += 1
                        if sge['search_angle']: items.append(self.make_item("搜索角度", f"{sge['search_angle']:.0f}", o, unit="°")); o += 1
                        if sge['max_yaw']: items.append(self.make_item("最大转向角", f"{sge['max_yaw']:.0f}", o, unit="°")); o += 1
                        if sge['max_vertical_speed']: items.append(self.make_item("最大垂直速度", f"{sge['max_vertical_speed']:.2f}", o, unit="kts")); o += 1
                        if sge['max_depth_level']: items.append(self.make_item("最大深度级别", f"{sge['max_depth_level']:.0f}", o)); o += 1
                        if sge['target_lost_degradation_time']: items.append(self.make_item("丢失目标降级时间", f"{sge['target_lost_degradation_time']:.1f}", o, unit="s")); o += 1
                else:
                    items.append(self.make_item(aname, "", o)); o += 1
        if items:
            result[letter] = items

    def _build_aa(self, conn, vc, ship_id, letter, result):
        items = []
        o = 0
        auras = {"Far": None, "Medium": None, "Near": None}
        bubble_data = {}
        gun_list = []
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
        if any(v is not None for v in auras.values()):
            labels = {"Far": "远程", "Medium": "中程", "Near": "近程"}
            for key in ("Far", "Medium", "Near"):
                info = auras[key]
                if info is not None:
                    dps_val, hit_chance, max_d, min_d = info
                    items.append(self.make_item(f"{labels[key]}防空炮", "", o, row_type="header")); o += 1
                    items.append(self.make_item("伤害", f"{dps_val:.0f}", o)); o += 1
                    if hit_chance is not None:
                        items.append(self.make_item("命中率", f"{hit_chance*100:.0f}", o, unit="%")); o += 1
                    if min_d is not None and max_d is not None:
                        items.append(self.make_item("射程", f"{min_d:.0f} ~ {max_d:.0f}", o, unit="km")); o += 1
        if bubble_data:
            items.append(self.make_item("防空炮弹", "", o, row_type="header")); o += 1
            bd = bubble_data["dmg"]
            if bd:
                items.append(self.make_item("爆炸伤害", f"{bd:.0f}", o)); o += 1
            bc = bubble_data.get("hit")
            if bc is not None:
                items.append(self.make_item("命中率", f"{bc*100:.0f}", o, unit="%")); o += 1
            bmin = bubble_data.get("min")
            bmax = bubble_data.get("max")
            if bmin is not None and bmax is not None:
                items.append(self.make_item("射程", f"{bmin:.0f} ~ {bmax:.0f}", o, unit="km")); o += 1
            bcnt = bubble_data.get("count")
            if bcnt:
                items.append(self.make_item("一次齐射数量", f"{bcnt:.0f}", o)); o += 1
        if items:
            result[letter] = items

    def _build_depth_charge(self, conn, vc, ship_id, letter, result):
        items = []
        o = 0
        for d in conn.execute(
            "SELECT * FROM ship_module_depth_charge WHERE version_code=? AND ship_id=? AND config_group LIKE ?",
            (vc, ship_id, f"{letter}%")).fetchall():
            gname = self.resolve_name('gun', d['gun_name']) or d['gun_name']
            items.append(self.make_item("深弹名称", f"{gname} x{d['count']}", o)); o += 1
            if d['reload_time']: items.append(self.make_item("装填时间", str(d['reload_time']), o, unit="s")); o += 1
            if d['shot_delay']: items.append(self.make_item("发射间隔", str(d['shot_delay']), o, unit="s")); o += 1
            if d['max_packs']: items.append(self.make_item("最大组数", str(d['max_packs']), o)); o += 1
            if d['num_shots']: items.append(self.make_item("每组数量", str(d['num_shots']), o)); o += 1
            if d['damage']: items.append(self.make_item("标伤", f"{d['damage']:.0f}", o)); o += 1
            if d['dc_speed']: items.append(self.make_item("下沉速度", f"{d['dc_speed']:.2f}", o, unit="m/s")); o += 1
            if d['dc_timer']: items.append(self.make_item("引信定时", f"{d['dc_timer']:.2f}", o, unit="s")); o += 1
            if d['dc_max_depth']: items.append(self.make_item("最大深度", f"{d['dc_max_depth']:.0f}", o, unit="m")); o += 1
            if d['depth_splash_size']: items.append(self.make_item("溅射范围", f"{d['depth_splash_size']:.2f}", o, unit="m")); o += 1
        if items:
            result[letter] = items

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
            "Fighter": "攻击机", "DiveBomber": "轰炸机",
            "TorpedoBomber": "鱼雷机", "SkipBomber": "弹跳轰炸机",
        }
        # 按 plane_type 分组
        by_type: dict[str, list] = {}
        for r in all_rows:
            pt = r.get('plane_type') or '其他'
            by_type.setdefault(pt, []).append(r)

        # 构建次级菜单内容：sub_labels + sub_keys + sub_contents
        sub_labels: list[str] = []
        sub_keys: dict[str, str] = {}  # 显示名称 → 内部类型 key
        sub_contents: dict = {}
        for ptype in ("Fighter", "DiveBomber", "TorpedoBomber", "SkipBomber", "其他"):
            rows = by_type.get(ptype)
            if not rows:
                continue
            label = TYPE_LABEL.get(ptype, ptype)
            sub_labels.append(label)
            sub_keys[label] = ptype  # 如 "攻击机" → "Fighter"
            # 按 (config_group, plane_name) 分组，不同机组分开显示
            prefix_map: dict[str, list] = {}
            for r in rows:
                cg = r.get('config_group') or ""
                pn = r.get('plane_name', '')
                key = f"{cg}|{pn}" if pn else cg
                prefix_map.setdefault(key, []).append(r)
            cfg_keys = sorted(prefix_map.keys(), key=lambda x: (x == "", x))
            config_labels: list[str] = []
            config_contents: dict[str, dict] = {}  # internal_key -> {"items": [...], ...}
            config_label_map: dict[str, str] = {}  # display_name -> internal_key
            ammo_map = self.get_name_map("ammo")
            for key in cfg_keys:
                # 提取显示名：取 plane_name 的可读名称
                parts = key.split("|", 1)
                if len(parts) > 1:
                    mr_part, pn_part = parts
                    disp_name = self.resolve_plane(pn_part) or pn_part
                else:
                    disp_name = key
                config_labels.append(disp_name)  # 按钮显示名
                config_label_map[disp_name] = key  # 显示名 → 内部键
                items: list[dict] = []
                raw_ammo_types: list[dict] = []
                raw_consumables: list[dict] = []
                o = 0
                group = prefix_map[key]
                for p in group:
                    pn = p.get('plane_name', '')
                    display_name = self.resolve_plane(pn)
                    items.append(self.make_item("飞机型号", display_name, o)); o += 1
                    # plane_basic_info
                    pi = conn.execute(
                        "SELECT * FROM plane_basic_info WHERE version_code=? AND plane_id=?",
                        (vc, self.resolve_plane_id(pn))).fetchone()
                    pid = {}
                    if pi:
                        pid = dict(pi)
                        if pid.get('plane_level'): items.append(self.make_item("飞机等级", str(pid['plane_level']), o)); o += 1
                        smwb = pid.get('speed_move_with_bomb')
                        if smwb:
                            max_mul = pid.get('speed_max_mult')
                            min_mul = pid.get('speed_min_mult')
                            items.append(self.make_item("巡航速度", str(smwb), o, unit="kts")); o += 1
                            if max_mul: items.append(self.make_item("最大速度", f"{smwb * max_mul:.2f}", o, unit="kts")); o += 1
                            if min_mul: items.append(self.make_item("最小速度", f"{smwb * min_mul:.2f}", o, unit="kts")); o += 1
                        else:
                            if pid.get('max_speed'): items.append(self.make_item("航速", str(pid['max_speed']), o, unit="kts")); o += 1
                            if pid.get('cruising_speed'): items.append(self.make_item("巡航速度", str(pid['cruising_speed']), o, unit="kts")); o += 1
                        if pid.get('hp'): items.append(self.make_item("单架飞机血量", str(pid['hp']), o)); o += 1
                        ac = pid.get('attack_count') or 0
                        if ac: items.append(self.make_item("载弹量", str(ac), o)); o += 1
                        if pid.get('attack_cooldown'): items.append(self.make_item("攻击冷却时间", str(pid['attack_cooldown']), o, unit="s")); o += 1
                        if pid.get('arrange_size') and pid['arrange_size'] > 0:
                            items.append(self.make_item("中队规模", str(pid['arrange_size']), o)); o += 1
                        if pid.get('angle_of_climb'): items.append(self.make_item("爬升角度", str(pid['angle_of_climb']), o, unit="°")); o += 1
                        if pid.get('angle_of_dive'): items.append(self.make_item("俯冲角度", str(pid['angle_of_dive']), o, unit="°")); o += 1
                        if pid.get('attack_angle') is not None: items.append(self.make_item("攻击角度", str(pid['attack_angle']), o, unit="°")); o += 1
                        if pid.get('preparation_time'): items.append(self.make_item("准备时间", str(pid['preparation_time']), o, unit="s")); o += 1
                        if pid.get('preparation_accel_increase') is not None:
                            items.append(self.make_item("准备缩圈速度", str(pid['preparation_accel_increase']), o)); o += 1
                        if pid.get('preparation_accel_decrease') is not None:
                            items.append(self.make_item("准备扩圈速度", str(abs(pid['preparation_accel_decrease'])), o)); o += 1
                        if pid.get('aiming_time'): items.append(self.make_item("瞄准时间", str(pid['aiming_time']), o, unit="s")); o += 1
                        if pid.get('aiming_accel_increase') is not None:
                            items.append(self.make_item("瞄准缩圈速度", str(pid['aiming_accel_increase']), o)); o += 1
                        if pid.get('aiming_accel_decrease') is not None:
                            items.append(self.make_item("瞄准扩圈速度", str(abs(pid['aiming_accel_decrease'])), o)); o += 1
                        if pid.get('post_attack_invulnerability_duration'):
                            items.append(self.make_item("攻击后无敌时间", str(pid['post_attack_invulnerability_duration']), o, unit="s")); o += 1
                        if pid.get('flight_height'): items.append(self.make_item("飞行高度", str(pid['flight_height']), o)); o += 1
                        if pid.get('attacker_size'): items.append(self.make_item("攻击编队大小", str(pid['attacker_size']), o)); o += 1
                        if pid.get('num_planes_in_squadron'): items.append(self.make_item("中队飞机数量", str(pid['num_planes_in_squadron']), o)); o += 1
                        if pid.get('visibility_factor') is not None: items.append(self.make_item("被侦测距离", str(pid['visibility_factor']), o, unit="km")); o += 1
                        if pid.get('species') == "Skip":
                            if pid.get('skip_height') is not None: items.append(self.make_item("弹跳高度", str(pid['skip_height']), o)); o += 1
                            if pid.get('aiming_height') is not None: items.append(self.make_item("瞄准视角高度", str(pid['aiming_height']), o)); o += 1
                        # 散布
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
                            mins_x = mins_x or 1.0; mins_y = mins_y or 1.0
                            def _rnd(v): return int(v + 0.5)
                            min_outer = (_rnd(oss_x * mins_x * _K), _rnd(oss_y * mins_y * _K))
                            max_outer = (_rnd(oss_x * maxs_x * _K), _rnd(oss_y * maxs_y * _K))
                            min_inner = (_rnd(iss_x * mins_x * _K), _rnd(iss_y * mins_y * _K))
                            max_inner = (_rnd(iss_x * maxs_x * _K), _rnd(iss_y * maxs_y * _K))
                            if ibp is not None: items.append(self.make_item("核心投弹", f"{int(ibp)}%", o)); o += 1
                            items.append(self.make_item("散布相关", "", o, row_type="header")); o += 1
                            items.append(self.make_item("最大散布", f"{max_outer[0]}x{max_outer[1]}", o)); o += 1
                            items.append(self.make_item("最小散布", f"{min_outer[0]}x{min_outer[1]}", o)); o += 1
                            items.append(self.make_item("最大散布内圈", f"{max_inner[0]}x{max_inner[1]}", o)); o += 1
                            items.append(self.make_item("最小散布内圈", f"{min_inner[0]}x{min_inner[1]}", o)); o += 1
                        elif pid.get('max_spread') is not None:
                            items.append(self.make_item("最大散布", str(pid['max_spread']), o)); o += 1
                            if pid.get('min_spread') is not None: items.append(self.make_item("最小散布", str(pid['min_spread']), o)); o += 1
                        # 机库
                        items.append(self.make_item("机库", "", o, row_type="header")); o += 1
                        if pid.get('hangar_max_value') is not None: items.append(self.make_item("最大可用数量", f"{pid['hangar_max_value']} 架", o)); o += 1
                        if pid.get('hangar_start_value') is not None: items.append(self.make_item("开局可用数量", f"{pid['hangar_start_value']} 架", o)); o += 1
                        if pid.get('hangar_restore_amount') is not None: items.append(self.make_item("每次整备数量", f"{pid['hangar_restore_amount']}架", o)); o += 1
                        if pid.get('hangar_time_to_restore') is not None: items.append(self.make_item("每次整备时间", str(pid['hangar_time_to_restore']), o, unit="s")); o += 1
                        bname = pid.get('bomb_name') or ""
                    else:
                        ac = 0; bname = ""
                    # ── 弹药数据（收集到 raw_ammo_types，类似火炮 _collect_ammo_types）──
                    arm = p.get('armament_name') or ""
                    proj_id = arm or bname
                    if proj_id:
                        pbi = conn.execute(
                            "SELECT species, ammo_type FROM projectile_basic_info WHERE version_code=? AND projectile_id=?",
                            (vc, proj_id)).fetchone()
                        if pbi:
                            species = pbi['species'] or ""
                            atype = pbi['ammo_type'] or ""
                            ammo_name = ammo_map.get(proj_id.upper(), self.resolve_name('ammo', proj_id) or proj_id)
                            detail_items: list[dict] = []
                            di = 0
                            _ac = "alpha_damage, bullet_krupp, alpha_piercing_he, alpha_piercing_cs, bullet_speed, explosion_radius, burn_prob, bullet_diameter, bullet_air_drag, bullet_always_ricochet_at, bullet_ricochet_at, bullet_detonator, bullet_detonator_threshold, bullet_cap_normalize_max"
                            _bc = f"damage, skips_json, max_skip_angle, {_ac}"
                            if species in ("Bullet", "HE"):
                                be = conn.execute(f"SELECT {_ac} FROM projectile_bullet_ext WHERE version_code=? AND projectile_id=?", (vc, proj_id)).fetchone()
                                if be:
                                    if be['alpha_damage']: detail_items.append(self.make_item("标伤", f"{be['alpha_damage']:.0f}", di)); di += 1
                                    detail_items.append(self.make_item("弹种", atype, di)); di += 1
                                    di = self._append_ammo_pen(detail_items, be, atype, di)
                                    if be['bullet_speed']: detail_items.append(self.make_item("弹速", f"{be['bullet_speed']:.0f}", di, unit="m/s")); di += 1
                                    if be['explosion_radius']: detail_items.append(self.make_item("爆炸半径", f"{be['explosion_radius']:.2f}", di, unit="m")); di += 1
                                    if be['burn_prob'] is not None: detail_items.append(self.make_item("起火概率", f"{be['burn_prob']*100:.2f}", di, unit="%")); di += 1
                                    di = self._append_ammo_extra(detail_items, be, atype, di)
                            elif species == "Bomb":
                                be = conn.execute(f"SELECT {_bc} FROM projectile_bomb_ext WHERE version_code=? AND projectile_id=?", (vc, proj_id)).fetchone()
                                if be:
                                    if be['alpha_damage']: detail_items.append(self.make_item("标伤", f"{be['alpha_damage']:.0f}", di)); di += 1
                                    detail_items.append(self.make_item("弹种", atype, di)); di += 1
                                    di = self._append_ammo_pen(detail_items, be, atype, di)
                                    if be['bullet_speed']: detail_items.append(self.make_item("弹速", f"{be['bullet_speed']:.0f}", di, unit="m/s")); di += 1
                                    if be['explosion_radius']: detail_items.append(self.make_item("爆炸半径", f"{be['explosion_radius']:.2f}", di, unit="m")); di += 1
                                    if be['burn_prob'] is not None: detail_items.append(self.make_item("起火概率", f"{be['burn_prob']*100:.2f}", di, unit="%")); di += 1
                                    di = self._append_ammo_extra(detail_items, be, atype, di)
                                    di = self._append_skip_data(detail_items, be, di)
                            elif species == "SkipBomb":
                                be = conn.execute(f"SELECT {_bc} FROM projectile_bomb_ext WHERE version_code=? AND projectile_id=?", (vc, proj_id)).fetchone()
                                if be:
                                    if be['alpha_damage']: detail_items.append(self.make_item("标伤", f"{be['alpha_damage']:.0f}", di)); di += 1
                                    detail_items.append(self.make_item("弹种", atype, di)); di += 1
                                    di = self._append_ammo_pen(detail_items, be, atype, di)
                                    if be['bullet_speed']: detail_items.append(self.make_item("弹速", f"{be['bullet_speed']:.0f}", di, unit="m/s")); di += 1
                                    if be['explosion_radius']: detail_items.append(self.make_item("爆炸半径", f"{be['explosion_radius']:.2f}", di, unit="m")); di += 1
                                    if be['burn_prob'] is not None: detail_items.append(self.make_item("起火概率", f"{be['burn_prob']*100:.2f}", di, unit="%")); di += 1
                                    di = self._append_ammo_extra(detail_items, be, atype, di)
                                    di = self._append_skip_data(detail_items, be, di)
                            elif species == "Rocket":
                                re = conn.execute(f"SELECT damage, {_ac} FROM projectile_rocket_ext WHERE version_code=? AND projectile_id=?", (vc, proj_id)).fetchone()
                                if re:
                                    if re['alpha_damage']: detail_items.append(self.make_item("标伤", f"{re['alpha_damage']:.0f}", di)); di += 1
                                    detail_items.append(self.make_item("弹种", atype, di)); di += 1
                                    di = self._append_ammo_pen(detail_items, re, atype, di)
                                    if re['bullet_speed']: detail_items.append(self.make_item("弹速", f"{re['bullet_speed']:.0f}", di, unit="m/s")); di += 1
                                    if re['explosion_radius']: detail_items.append(self.make_item("爆炸半径", f"{re['explosion_radius']:.2f}", di, unit="m")); di += 1
                                    if re['burn_prob'] is not None: detail_items.append(self.make_item("起火概率", f"{re['burn_prob']*100:.2f}", di, unit="%")); di += 1
                                    di = self._append_ammo_extra(detail_items, re, atype, di)
                                asq = conn.execute("SELECT attack_sequence_durations FROM projectile_rocket_ext WHERE version_code=? AND projectile_id=?", (vc, proj_id)).fetchone()
                                if asq and asq['attack_sequence_durations']:
                                    di = self._append_strafe_time(detail_items, asq['attack_sequence_durations'], di)
                            elif species in ("Torpedo", "TorpedoBomber"):
                                te = conn.execute(
                                    "SELECT alpha_damage, damage, torpedo_speed, torpedo_max_dist, torpedo_visibility, "
                                    "torpedo_arming_time, burn_prob, uw_critical, flood_generation, is_deep_water, deep_water_ignore_classes, alert_dist "
                                    "FROM projectile_torpedo_ext WHERE version_code=? AND projectile_id=?", (vc, proj_id)).fetchone()
                                if te:
                                    sge = conn.execute(
                                        "SELECT max_yaw, drop_dist_aircarrier, drop_dist_battleship, drop_dist_cruiser, "
                                        "drop_dist_destroyer, drop_dist_submarine, drop_dist_default "
                                        "FROM projectile_torpedo_sub_guidance_ext WHERE version_code=? AND projectile_id=?", (vc, proj_id)).fetchone()
                                    is_guided = sge is not None; is_deep = te['is_deep_water']; is_burn = bool(te['burn_prob'])
                                    dtype = "声呐导向鱼雷" if is_guided else ("深水鱼雷" if is_deep else ("热能鱼雷" if is_burn else "鱼雷"))
                                    ad = te['alpha_damage'] or 0
                                    if ad: detail_items.append(self.make_item("标伤", f"{ad * 0.33:.0f}", di)); di += 1
                                    detail_items.append(self.make_item("弹种", atype, di)); di += 1
                                    detail_items.append(self.make_item("类型", dtype, di)); di += 1
                                    if is_deep and te['deep_water_ignore_classes']: detail_items.append(self.make_item("无法攻击目标", te['deep_water_ignore_classes'], di)); di += 1
                                    if te['torpedo_speed']: detail_items.append(self.make_item("航速", f"{te['torpedo_speed']:.0f}", di, unit="kts")); di += 1
                                    if te['torpedo_max_dist'] is not None: detail_items.append(self.make_item("最大射程", f"{(te['torpedo_max_dist'] * 30) / 1000:.2f}", di, unit="km")); di += 1
                                    if te['flood_generation'] and te['uw_critical']: detail_items.append(self.make_item("基础漏水系数", f"{te['uw_critical']:.2f}", di)); di += 1
                                    if te['torpedo_visibility']: detail_items.append(self.make_item("鱼雷被侦测距离", f"{te['torpedo_visibility']:.2f}", di, unit="km")); di += 1
                                    if te['torpedo_arming_time']: detail_items.append(self.make_item("鱼雷上浮时间", f"{te['torpedo_arming_time']:.2f}", di, unit="s")); di += 1
                                    if is_burn and te['burn_prob']: detail_items.append(self.make_item("基础点火率", f"{te['burn_prob']*100:.0f}", di, unit="%")); di += 1
                                    if is_guided:
                                        if sge['max_yaw']: detail_items.append(self.make_item("最大转向角", str(sge['max_yaw']), di, unit="°")); di += 1
                                        drop_parts = []
                                        for ship_cls, col in [("航母","drop_dist_aircarrier"),("战列舰","drop_dist_battleship"),("巡洋舰","drop_dist_cruiser"),("驱逐舰","drop_dist_destroyer"),("潜艇","drop_dist_submarine"),("默认","drop_dist_default")]:
                                            if sge[col] is not None: drop_parts.append(f"{ship_cls}: {sge[col]} m")
                                        if drop_parts: detail_items.append(self.make_item("放弃追踪距离", ' | '.join(drop_parts), di)); di += 1
                            raw_ammo_types.append({
                                "ammo_id": proj_id, "name": ammo_name,
                                "species": species, "ammo_type": atype,
                                "detail_items": detail_items,
                            })
                    # ── 消耗品数据（收集到 raw_consumables，类似 _append_consumables）──
                    for si in range(5):
                        slot_val = pid.get(f'ability_slot_{si}')
                        if not slot_val:
                            continue
                        parts = slot_val.split('|', 1)
                        aid = parts[0]
                        variant = parts[1] if len(parts) > 1 else ""
                        aname = self.resolve_name("consumable", aid)
                        if variant:
                            cfg = conn.execute(
                                "SELECT consumable_type, extra_json FROM consumable_configs "
                                "WHERE version_code=? AND consumable_id=? AND config_key=?",
                                (vc, aid, variant)).fetchone()
                        else:
                            cfg = None
                        con_detail: list[dict] = []
                        cd2 = 0
                        con_detail.append(self.make_item("名称", aname, cd2)); cd2 += 1
                        if cfg:
                            try: cd = json.loads(cfg['extra_json'] or '{}')
                            except Exception: cd = {}
                            ct = cfg['consumable_type'] or cd.get('consumableType', '')
                            num = cd.get('numConsumables')
                            prep = cd.get('preparationTime', 0)
                            cd_time = cd.get('reloadTime', 0)
                            wt = cd.get('workTime', 0)
                            auto = cd.get('isAutoConsumable', False)
                            con_detail.append(self.make_item("类型", ct, cd2)); cd2 += 1
                            if num is not None: con_detail.append(self.make_item("数量", '无限' if num == -1 else str(num), cd2)); cd2 += 1
                            if auto: con_detail.append(self.make_item("自动使用", "是", cd2)); cd2 += 1
                            if prep: con_detail.append(self.make_item("准备时间", str(prep), cd2, unit="s")); cd2 += 1
                            if cd_time: con_detail.append(self.make_item("冷却时间", str(cd_time), cd2, unit="s")); cd2 += 1
                            if wt: con_detail.append(self.make_item("持续时间", str(wt), cd2, unit="s")); cd2 += 1
                            con_detail.append(self.make_item("消耗品效果", "", cd2, row_type="header")); cd2 += 1
                            if ct == "crashCrew":
                                con_detail.append(self.make_item("说明", "扑灭起火、清除进水、并修复受损配件。", cd2)); cd2 += 1
                            elif ct == "healForsage":
                                bc = cd.get('boostCoeff', 0)
                                if bc: con_detail.append(self.make_item("加速倍率", f"{bc}倍", cd2)); cd2 += 1
                            elif ct in ("callFighters", "fighter"):
                                fn = cd.get('fightersName', '')
                                if fn: con_detail.append(self.make_item("战斗机名称", self.resolve_name('plane', fn) or fn, cd2)); cd2 += 1
                                con_detail.append(self.make_item("数量", str(cd.get('fightersNum', 0)), cd2)); cd2 += 1
                                con_detail.append(self.make_item("截击机", "是" if cd.get('isInterceptor', False) else "否", cd2)); cd2 += 1
                                dog = cd.get('dogFightTime', 0); fly = cd.get('flyAwayTime', 0)
                                if dog: con_detail.append(self.make_item("狗斗", str(dog), cd2, unit="s")); cd2 += 1
                                if fly: con_detail.append(self.make_item("离开", str(fly), cd2, unit="s")); cd2 += 1
                                rk = cd.get('distanceToKill', 0)
                                if rk: con_detail.append(self.make_item("巡逻半径", f"{rk/10:.2f}", cd2, unit="km")); cd2 += 1
                            elif ct in ("regenerateHealth", "regenCrew"):
                                rr = cd.get('regenerationRate', 0) or cd.get('regenerationHPSpeed', 0)
                                if rr: con_detail.append(self.make_item("每秒回复血量", f"{rr*100:.0f}", cd2, unit="%")); cd2 += 1
                                delay = cd.get('regenerationDelay', 0)
                                if delay: con_detail.append(self.make_item("回复延迟", str(delay), cd2, unit="s")); cd2 += 1
                            elif ct == "scout":
                                dc = (float(cd.get('artilleryDistCoeff', 0) or 1) - 1)
                                con_detail.append(self.make_item("主炮射程", f"{dc*100:+.2f}", cd2, unit="%")); cd2 += 1
                                modifiers = cd.get('modifiers')
                                if modifiers and isinstance(modifiers, dict):
                                    for mk, mv in sorted(modifiers.items()):
                                        con_detail.append(self.make_item(Mapping.MODIFIER_MAP.get(mk, mk), f"{(mv-1)*100:+.0f}", cd2, unit="%")); cd2 += 1
                            elif ct == "smokeGenerator":
                                r = float(cd.get('radius', 0) or 0)
                                con_detail.append(self.make_item("烟雾半径", f"{r*3:.2f}", cd2, unit="m")); cd2 += 1
                                h = cd.get('height', 0)
                                if h: con_detail.append(self.make_item("烟雾高度", str(h), cd2, unit="m")); cd2 += 1
                                sp = cd.get('speedLimit', 0); lt = cd.get('lifeTime', 0)
                                if sp: con_detail.append(self.make_item("速度限制", str(sp), cd2, unit="kts")); cd2 += 1
                                if lt: con_detail.append(self.make_item("扩散时间", str(lt), cd2, unit="s")); cd2 += 1
                            elif ct == "speedBoosters":
                                bc = float(cd.get('boostCoeff', 0) or 0)
                                con_detail.append(self.make_item("最高航速", f"{bc*100:+.2f}", cd2, unit="%")); cd2 += 1
                            elif ct == "airDefenseDisp":
                                adm = cd.get('areaDamageMultiplier', 0); bdm = cd.get('bubbleDamageMultiplier', 0)
                                if adm: con_detail.append(self.make_item("防空区域秒伤", f"{adm*100:+.2f}", cd2, unit="%")); cd2 += 1
                                if bdm: con_detail.append(self.make_item("黑云伤害", f"{bdm*100:+.2f}", cd2, unit="%")); cd2 += 1
                            elif ct == "planeSmokeGenerator":
                                ad = cd.get('activationDelay', 0); r = float(cd.get('radius', 0) or 0)
                                if ad: con_detail.append(self.make_item("生效延迟", str(ad), cd2, unit="s")); cd2 += 1
                                if r: con_detail.append(self.make_item("烟雾半径", f"{r*3:.2f}", cd2, unit="m")); cd2 += 1
                        raw_consumables.append({
                            "consumable_id": aid,
                            "config_key": variant,
                            "display_name": aname,
                            "detail_items": con_detail,
                        })
                config_contents[key] = {
                    "items": items,
                    "raw_ammo_types": raw_ammo_types,
                    "raw_consumables": raw_consumables,
                }
            sub_contents[label] = {"config_labels": config_labels, "config_contents": config_contents, "config_label_map": config_label_map}

        self._aircraft_sub_info = {"舰载机": {"sub_labels": sub_labels, "sub_keys": sub_keys, "sub_contents": sub_contents}}
        return self.make_section("舰载机", [])
    def _build_air_support(self, conn, vc, ship_id, letter, result):
        items = []
        raw_ammo_types: list[dict] = []
        raw_consumables: list[dict] = []
        o = 0
        ammo_map = self.get_name_map("ammo")
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
                        if sp == "DepthCharge": label = "深水炸弹空袭"
                        elif sp in ("bomb", "Bomb"):
                            label = {"AP": "穿甲炸弹空袭", "HE": "高爆炸弹空袭", "SAP": "半穿甲炸弹空袭"}.get(at, "高爆炸弹空袭")
                        elif sp in ("rocket", "Rocket"):
                            label = {"AP": "穿甲火箭空袭", "HE": "高爆火箭空袭"}.get(at, "火箭空袭")
                        else: label = f"未知空袭({sp})"
                    else: label = "未知空袭"
                else: label = "未知空袭"
            else:
                label = TYPE_LABEL.get(st, st)
            items.append(self.make_item(label, "", o, row_type="header")); o += 1
            for s in group:
                arm = s['armament_name'] or ""
                sname = self.resolve_plane(s['plane_name']) or s['plane_name']
                items.append(self.make_item("飞机型号", sname, o)); o += 1
                if s['charges'] is not None: items.append(self.make_item("最大充能次数", str(s['charges']), o)); o += 1
                if s['reload_time']: items.append(self.make_item("装填时间", str(s['reload_time']), o, unit="s")); o += 1
                if s['work_time']: items.append(self.make_item("持续时间", str(s['work_time']), o, unit="s")); o += 1
                mr = s['max_range']; mir = s.get('min_range')
                def _fmt_range(v):
                    if v is None: return None
                    return "全图" if v == float('inf') else f"{v/1000:.2f}"
                rtxt = _fmt_range(mr); rtxt2 = _fmt_range(mir)
                if rtxt: items.append(self.make_item("最大距离", rtxt, o, unit="km")); o += 1
                if rtxt2: items.append(self.make_item("最小距离", rtxt2, o, unit="km")); o += 1
                pi = conn.execute(
                    "SELECT * FROM plane_basic_info WHERE version_code=? AND plane_id=?",
                    (vc, self.resolve_plane_id(s['plane_name']))).fetchone()
                pid = dict(pi) if pi else {}
                if pid:
                    smwb = pid.get('speed_move_with_bomb')
                    if smwb:
                        max_mul = pid.get('speed_max_mult'); min_mul = pid.get('speed_min_mult')
                        items.append(self.make_item("巡航速度", str(smwb), o, unit="kts")); o += 1
                        if max_mul: items.append(self.make_item("最大速度", f"{smwb * max_mul:.2f}", o, unit="kts")); o += 1
                        if min_mul: items.append(self.make_item("最小速度", f"{smwb * min_mul:.2f}", o, unit="kts")); o += 1
                    else:
                        if pid.get('max_speed'): items.append(self.make_item("航速", str(pid['max_speed']), o, unit="kts")); o += 1
                        if pid.get('cruising_speed'): items.append(self.make_item("巡航速度", str(pid['cruising_speed']), o, unit="kts")); o += 1
                    if pid.get('hp'): items.append(self.make_item("单架飞机血量", f"{pid['hp']:.0f}", o)); o += 1
                    if pid.get('flight_height'): items.append(self.make_item("飞行高度", str(pid['flight_height']), o)); o += 1
                    if pid.get('attacker_size'): items.append(self.make_item("攻击编组数量", str(pid['attacker_size']), o)); o += 1
                    if pid.get('visibility_factor') is not None: items.append(self.make_item("被侦测距离", str(pid['visibility_factor']), o, unit="km")); o += 1
                    if not arm and pid.get('bomb_name'): arm = pid['bomb_name']
                    if arm and pid.get('attack_count'): items.append(self.make_item("载弹量", str(pid['attack_count']), o)); o += 1
                # ── 弹药数据 ──
                if arm:
                    pbi = conn.execute(
                        "SELECT species, ammo_type FROM projectile_basic_info WHERE version_code=? AND projectile_id=?",
                        (vc, arm)).fetchone()
                    if pbi:
                        species = pbi['species'] or ""
                        atype = pbi['ammo_type'] or ""
                        ammo_name = ammo_map.get(arm.upper(), self.resolve_name('ammo', arm) or arm)
                        # 添加弹药占位，供 _build_weapon_widget 计数用
                        items.append(self.make_item("弹药", ammo_name, o)); o += 1
                        detail_items: list[dict] = []
                        di = 0
                        _ac = "alpha_damage, bullet_krupp, alpha_piercing_he, alpha_piercing_cs, bullet_speed, explosion_radius, burn_prob, bullet_diameter, bullet_air_drag, bullet_always_ricochet_at, bullet_ricochet_at, bullet_detonator, bullet_detonator_threshold, bullet_cap_normalize_max"
                        _bc = f"damage, skips_json, max_skip_angle, {_ac}"
                        for tbl, cols in [("projectile_bullet_ext", _ac), ("projectile_bomb_ext", _bc),
                                           ("projectile_rocket_ext", f"damage, {_ac}"),
                                           ("projectile_depth_charge_ext", "damage, dc_speed, dc_timer, dc_max_depth, depth_splash_size")]:
                            ext = conn.execute(f"SELECT {cols} FROM {tbl} WHERE version_code=? AND projectile_id=?", (vc, arm)).fetchone()
                            if ext:
                                if tbl == "projectile_depth_charge_ext":
                                    if ext['damage']: detail_items.append(self.make_item("标伤", f"{ext['damage']:.0f}", di)); di += 1
                                    if ext['dc_speed']: detail_items.append(self.make_item("下沉速度", f"{ext['dc_speed']:.2f}", di, unit="m/s")); di += 1
                                    if ext['dc_timer']: detail_items.append(self.make_item("引信定时", f"{ext['dc_timer']:.2f}", di, unit="s")); di += 1
                                    if ext['dc_max_depth']: detail_items.append(self.make_item("最大深度", f"{ext['dc_max_depth']:.0f}", di, unit="m")); di += 1
                                    if ext['depth_splash_size']: detail_items.append(self.make_item("溅射范围", f"{ext['depth_splash_size']:.2f}", di, unit="m")); di += 1
                                else:
                                    if ext['alpha_damage']: detail_items.append(self.make_item("标伤", f"{ext['alpha_damage']:.0f}", di)); di += 1
                                    detail_items.append(self.make_item("弹种", atype, di)); di += 1
                                    if atype == "HE":
                                        if ext['alpha_piercing_he']: detail_items.append(self.make_item("穿深", f"{ext['alpha_piercing_he']:.1f}", di, unit="mm")); di += 1
                                    elif atype == "CS":
                                        if ext['alpha_piercing_cs']: detail_items.append(self.make_item("穿深", f"{ext['alpha_piercing_cs']:.1f}", di, unit="mm")); di += 1
                                    else:
                                        if ext['bullet_krupp']: detail_items.append(self.make_item("硬度", f"{ext['bullet_krupp']:.0f}", di)); di += 1
                                    if ext['bullet_speed']: detail_items.append(self.make_item("弹速", f"{ext['bullet_speed']:.0f}", di, unit="m/s")); di += 1
                                    if ext['explosion_radius']: detail_items.append(self.make_item("爆炸半径", f"{ext['explosion_radius']:.2f}", di, unit="m")); di += 1
                                    if ext['burn_prob'] is not None: detail_items.append(self.make_item("起火概率", f"{ext['burn_prob']*100:.2f}", di, unit="%")); di += 1
                                    if atype in ("AP", "CS"):
                                        if ext['bullet_air_drag']: detail_items.append(self.make_item("阻力系数", str(ext['bullet_air_drag']), di)); di += 1
                                        if ext['bullet_diameter']: detail_items.append(self.make_item("口径", f"{ext['bullet_diameter']*1000:.2f}", di, unit="mm")); di += 1
                                        if ext['bullet_always_ricochet_at']: detail_items.append(self.make_item("强制跳弹角", f"{ext['bullet_always_ricochet_at']:.0f}", di, unit="°")); di += 1
                                        if ext['bullet_ricochet_at']: detail_items.append(self.make_item("概率跳弹角", f"{ext['bullet_ricochet_at']:.0f}", di, unit="°")); di += 1
                                        if ext['bullet_cap_normalize_max']: detail_items.append(self.make_item("弹头转正角", f"{ext['bullet_cap_normalize_max']:.0f}", di, unit="°")); di += 1
                                        if atype == "AP":
                                            if ext['bullet_detonator']: detail_items.append(self.make_item("引信长度", f"{ext['bullet_detonator']:.0f}", di, unit="s")); di += 1
                                            if ext['bullet_detonator_threshold']: detail_items.append(self.make_item("引信触发阈值", f"{ext['bullet_detonator_threshold']:.0f}", di, unit="mm")); di += 1
                                # 跳弹数据
                                if tbl == "projectile_bomb_ext" and ext.get('skips_json'):
                                    try:
                                        skips = json.loads(ext['skips_json']) if isinstance(ext['skips_json'], str) else ext['skips_json']
                                        if isinstance(skips, (list, tuple)):
                                            detail_items.append(self.make_item("弹跳次数", f"{len(skips)} 次", di)); di += 1
                                            detail_items.append(self.make_item("总共落点段数", f"{len(skips) + 1} 段", di)); di += 1
                                        if ext.get('max_skip_angle'): detail_items.append(self.make_item("最大弹跳触发角度", f"{ext['max_skip_angle']:.0f}", di, unit="°")); di += 1
                                    except Exception: pass
                                # 扫射时间
                                if species == "Rocket":
                                    asq = conn.execute("SELECT attack_sequence_durations FROM projectile_rocket_ext WHERE version_code=? AND projectile_id=?", (vc, arm)).fetchone()
                                    if asq and asq['attack_sequence_durations']:
                                        try:
                                            seq = json.loads(asq['attack_sequence_durations']) if isinstance(asq['attack_sequence_durations'], str) else asq['attack_sequence_durations']
                                            if isinstance(seq, (list, tuple)) and len(seq) >= 2:
                                                detail_items.append(self.make_item("扫射时间", f"{sum(seq):.1f}", di, unit="s")); di += 1
                                        except Exception: pass
                                break
                        else:
                            # 非弹药类武器（鱼雷）
                            te = conn.execute(
                                "SELECT alpha_damage, damage, torpedo_speed, torpedo_max_dist, torpedo_visibility, torpedo_arming_time, flood_generation, is_deep_water, deep_water_ignore_classes "
                                "FROM projectile_torpedo_ext WHERE version_code=? AND projectile_id=?", (vc, arm)).fetchone()
                            if te:
                                sge = conn.execute("SELECT max_yaw FROM projectile_torpedo_sub_guidance_ext WHERE version_code=? AND projectile_id=?", (vc, arm)).fetchone()
                                is_guided = sge is not None; is_deep = te['is_deep_water']
                                if is_guided: detail_items.append(self.make_item("类型", "声呐导向鱼雷", di)); di += 1
                                elif is_deep: detail_items.append(self.make_item("类型", "深水鱼雷", di)); di += 1
                                ad = te['alpha_damage'] or 0
                                if ad: detail_items.append(self.make_item("标伤", f"{ad * 0.33:.0f}", di)); di += 1
                                if te['torpedo_speed']: detail_items.append(self.make_item("航速", f"{te['torpedo_speed']:.0f}", di, unit="kts")); di += 1
                                if te['torpedo_max_dist'] is not None: detail_items.append(self.make_item("最大射程", f"{(te['torpedo_max_dist'] * 30) / 1000:.2f}", di, unit="km")); di += 1
                                fg = te['flood_generation'] or 0
                                if fg: detail_items.append(self.make_item("基础漏水率", f"{fg * 100:.0f}", di, unit="%")); di += 1
                        raw_ammo_types.append({
                            "ammo_id": arm, "name": ammo_name,
                            "species": species, "ammo_type": atype,
                            "detail_items": detail_items,
                        })
        if items or raw_ammo_types:
            result[letter] = {"items": items, "raw_ammo_types": raw_ammo_types}

    def _build_sub_section_info(self, conn, vc, ship_id, sections):
        """构建子分类映射：模块类型(船体/主炮) → {A/B/C 配置 → items}"""
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

        # 为每个 section label 提取该 section 下按 letter 拆分的 items
        sub_info: dict[str, dict] = {}
        for section in sections:
            label = section.get("label", "")
            items = section.get("items", [])
            raw_ammo = section.get("raw_ammo_types", [])
            # 按 header 行分组：找到 ── X 配置 ── 标记，将后续 items 归入该 letter
            letter_contents: dict[str, list[dict]] = {}
            letter_raw_ammo: dict[str, list[dict]] = {}
            current_letter = None
            for item in items:
                if item.get("row_type") == "header":
                    hdr = item.get("name", "")
                    for lt in letters:
                        if f"── {lt} 配置 ──" == hdr:
                            current_letter = lt
                            letter_contents.setdefault(current_letter, [])
                            break
                elif current_letter is not None:
                    letter_contents.setdefault(current_letter, []).append(item)
            if raw_ammo:
                # 将 raw_ammo 按字母均分（各配置弹药数相同）
                per_letter = len(raw_ammo) // max(len(letter_contents), 1)
                for i, lt in enumerate(sorted(letter_contents.keys())):
                    start = i * per_letter
                    letter_raw_ammo[lt] = raw_ammo[start:start + per_letter]
            if letter_contents and len(letter_contents) > 1:
                sub_labels = sorted(letter_contents.keys())
                sub_contents = {}
                for l in sub_labels:
                    entry: dict = {"items": letter_contents[l]}
                    if letter_raw_ammo.get(l):
                        entry["raw_ammo_types"] = letter_raw_ammo[l]
                    sub_contents[f"{l} 配置"] = entry
                sub_info[label] = {
                    "sub_labels": [f"{l} 配置" for l in sub_labels],
                    "sub_contents": sub_contents,
                }
        return sub_info

    def _resolve_module_display_name(self, mid: str) -> str:
        """解析模块 ID 的显示名称。

        优先从 name_mappings 各分类中查找本地化名，
        其次尝试飞机前缀映射（PAUB→PAAB 等），
        若均无结果则以原始 ID 兜底。
        """
        if mid.endswith('Default'):
            return '默认'

        # resolve_name() 在未命中时返回 key 本身，无法用 or 链短路
        # 因此逐个分类检查 name != mid
        for cat in ('module_upgrade', 'gun', 'plane', 'ammo', 'consumable', 'modernization'):
            name = self.resolve_name(cat, mid)
            if name != mid:
                return name

        # 飞机前缀映射（PAUB→PAAB, PAUI→PAAF, …）
        plane_name = self.resolve_plane(mid)
        if plane_name and plane_name != mid:
            return plane_name

        return mid

    def _build_config_bar(self, conn, vc, ship_id, basic) -> dict:
        """构建顶部配置栏数据：模块/升级品/消耗品"""
        # 1. 模块配置组
        module_groups: dict[str, list[str]] = {}
        for r in conn.execute(
            "SELECT DISTINCT slot_type, config_group FROM ship_module_relations "
            "WHERE version_code=? AND ship_id=? AND config_group NOT LIKE '%special%' ORDER BY slot_type, config_group",
            (vc, ship_id)).fetchall():
            st = r["slot_type"] or "其他"
            cg = self._config_group_letter(r["config_group"])
            module_groups.setdefault(st, []).append(cg)

        # 2. 引擎
        engine_name = ""
        for r in conn.execute(
            "SELECT module_key FROM ship_module_engine WHERE version_code=? AND ship_id=?",
            (vc, ship_id)).fetchall():
            en = self.resolve_name('gun', r['module_key']) or r['module_key']
            if en:
                engine_name = en
                break

        # 3. 消耗品
        consumables: list[str] = []
        for r in conn.execute(
            "SELECT DISTINCT consumable_id FROM ship_consumable_slots WHERE version_code=? AND ship_id=? ORDER BY slot_index",
            (vc, ship_id)).fetchall():
            cn = self.resolve_name('consumable', r['consumable_id']) or r['consumable_id']
            if cn not in consumables:
                consumables.append(cn)

        # 4. 升级信息（ShipUpgradeInfo），解析模块名称
        upgrades: list[dict] = []
        for r in conn.execute(
            "SELECT upgrade_key, uc_type, components_json FROM ship_upgrade_info "
            "WHERE version_code=? AND ship_id=? ORDER BY upgrade_key",
            (vc, ship_id)).fetchall():
            comps = json.loads(r["components_json"] or "{}")
            # 解析每个模块 ID 的名称
            resolved_comps: dict[str, list[dict]] = {}
            for slot_type, mods in comps.items():
                resolved_mods = []
                for mid in mods:
                    display_name = self._resolve_module_display_name(mid)
                    resolved_mods.append({
                        "id": mid,
                        "name": display_name,
                    })
                resolved_comps[slot_type] = resolved_mods
            upgrades.append({
                "key": r["upgrade_key"],
                "key_name": self._resolve_module_display_name(r["upgrade_key"]),
                "type": r["uc_type"],
                "components": resolved_comps,
            })

        # 5. 舰船基本信息摘要
        from models.name_mapping import Mapping as NM2
        nation_name = ""
        nat_row = conn.execute(
            "SELECT nation FROM entity_registry WHERE version_code=? AND entity_id=?",
            (vc, ship_id)).fetchone()
        if nat_row:
            nation_name = NM2.NATION_MAP.get(nat_row[0], nat_row[0])

        return {
            "nation": nation_name,
            "tier": basic['tier'],
            "shiptype": self.resolve_enum("ship_class", basic['shiptype']) if basic['shiptype'] else "",
            "module_groups": module_groups,
            "engine": engine_name,
            "consumables": consumables,
            "upgrades": upgrades,
        }
