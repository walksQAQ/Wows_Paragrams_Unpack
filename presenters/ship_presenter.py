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
                for letter in letters:
                    letter_items = data.get(letter, [])
                    if letter_items:
                        if len(letters) > 1:
                            all_items.append(self.make_item(f"── {letter} 配置 ──", "", len(all_items), row_type="header"))
                        all_items.extend(letter_items)
                if all_items:
                    sections.append(self.make_section(label, all_items))
        # 舰载机独立处理：一个 section + 次级菜单
        plane_section = self._build_aircraft_panel(conn, vc, ship_id, letters, sections)
        if plane_section:
            sections.append(plane_section)
        # 空袭
        if asup_data:
            all_items: list[dict] = []
            for letter in letters:
                letter_items = asup_data.get(letter, [])
                if letter_items:
                    if len(letters) > 1:
                        all_items.append(self.make_item(f"── {letter} 配置 ──", "", len(all_items), row_type="header"))
                    all_items.extend(letter_items)
            if all_items:
                sections.append(self.make_section("支援", all_items))

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
            # 回复率
            hrp = h['hull_regen_part']
            crp = h['citadel_regen_part']
            if hrp is not None or crp is not None:
                hrp_str = f"{hrp*100:.0f}%" if hrp is not None else "N/A"
                crp_str = f"{crp*100:.0f}%" if crp is not None else "N/A"
                items.append(self.make_item("回复率 (船体/核心区)", f"{hrp_str}/{crp_str}", o)); o += 1

            for col, label, unit in [
                ("health", "基础血量", ""),
                ("max_speed", "最大航速", "节"),
                ("turning_radius", "转弯半径", "米"),
                ("rudder_time", "转舵时间", "秒"),
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
                        label, f"{val:.2f}", o, unit="公里",
                        details=[{"name": min_label, "value": f"{min_val:.2f}", "unit": "公里"}]
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
                    ("hydrophone_radius", "水听器工作半径", "公里"),
                    ("hydrophone_update_freq", "水听器更新周期", "秒"),
                    ("buoyancy_rudder_time", "水平舵转舵时间", "秒"),
                    ("max_buoyancy_speed", "最大上浮/下潜速度", "节"),
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
        items = self._render_weapon_groups(conn, vc, groups, ammo_map)
        if items:
            result[letter] = items

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
        """将分组后的武器数据渲染为 items"""
        items = []
        o = 0
        for grp in groups:
            g = grp["row"]
            total_count = grp["count"]
            drum = grp["drum"]
            ammo_ids = grp["ammo_ids"]
            gname = self.resolve_name('gun', g['module_key']) or g['module_key']
            items.append(self.make_item("火炮名称", f"{gname} x{total_count}", o)); o += 1
            if g['num_barrels']: items.append(self.make_item("联装数", f"{g['num_barrels']:.0f}", o)); o += 1
            if g['reload_time']: items.append(self.make_item("装填时间", str(g['reload_time']), o, unit="秒")); o += 1
            if g['max_range']: items.append(self.make_item("基础射程", f"{g['max_range']:.2f}", o, unit="公里")); o += 1
            # 散步公式
            ir, mr, id_dist = g['ideal_radius'], g['min_radius'], g['ideal_distance']
            if ir and mr and id_dist:
                slope = (ir - mr) / (id_dist / 1000) if id_dist else 0
                intercept = mr * 30
                items.append(self.make_item("横向散步公式", f"{slope:.2f}R + {intercept:.0f}", o)); o += 1
            # 纵向散步
            if g['radius_zero'] is not None and g['radius_max'] is not None:
                r0, rdelim, rmax, delim = g['radius_zero'], g['radius_delim'], g['radius_max'], g['delim']
                pct = f"{delim*100:.0f}%" if delim else "?"
                items.append(self.make_item("纵向散步系数", f"{r0} ~ {rdelim}(R={pct}) ~ {rmax}", o)); o += 1
            if g['sigma']: items.append(self.make_item("弹着群系数(Sigma)", str(g['sigma']), o)); o += 1
            if g.get('rotation_speed_h'): items.append(self.make_item("水平回转速度", f"{g['rotation_speed_h']:.1f}", o, unit="°/s")); o += 1
            if g.get('rotation_speed_v'): items.append(self.make_item("垂直回转速度", f"{g['rotation_speed_v']:.1f}", o, unit="°/s")); o += 1
            if g.get('caliber'): items.append(self.make_item("口径", f"{g['caliber']*1000:.0f}", o, unit="mm")); o += 1
            # 弹药
            for aid in ammo_ids:
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
                    items.append(self.make_item("可用炮弹", acn, o, row_type="header")); o += 1
                    if p['alpha_damage']: items.append(self.make_item("标伤", f"{p['alpha_damage']:.0f}", o)); o += 1
                    items.append(self.make_item("弹种", p['ammo_type'] or '?', o)); o += 1
                    items.append(self.make_item("炮弹详细属性", "", o, row_type="header")); o += 1
                    if p['explosion_radius']: items.append(self.make_item("炮弹爆炸半径", f"{p['explosion_radius']:.2f}", o, unit="米")); o += 1
                    if p['bullet_diameter']: items.append(self.make_item("炮弹口径", f"{p['bullet_diameter']*1000:.0f}", o, unit="mm")); o += 1
                    if p['bullet_speed']: items.append(self.make_item("炮弹初速", f"{p['bullet_speed']:.0f}", o, unit="m/s")); o += 1
                    if p['bullet_air_drag']: items.append(self.make_item("空阻系数", str(p['bullet_air_drag']), o)); o += 1
                    if p['bullet_mass']: items.append(self.make_item("炮弹重量", f"{p['bullet_mass']:.2f}", o, unit="kg")); o += 1
                    if at == 'HE':
                        if p['burn_prob'] is not None: items.append(self.make_item("起火率", f"{p['burn_prob']*100:.2f}", o, unit="%")); o += 1
                        if p['alpha_piercing_he']: items.append(self.make_item("HE穿深", f"{p['alpha_piercing_he']:.1f}", o, unit="mm")); o += 1
                    elif at == 'SAP':
                        if p['alpha_piercing_cs']: items.append(self.make_item("SAP穿深", f"{p['alpha_piercing_cs']:.1f}", o, unit="mm")); o += 1
                        rc1 = p['bullet_ricochet_at']
                        rc2 = p['bullet_always_ricochet_at']
                        if rc1 or rc2:
                            items.append(self.make_item("跳弹角度", f"{rc1:.0f}°/{rc2:.0f}°", o)); o += 1
                    elif at == 'AP':
                        if p['bullet_krupp']: items.append(self.make_item("弹头硬度", f"{p['bullet_krupp']:.0f}", o)); o += 1
                        if p['bullet_detonator'] is not None: items.append(self.make_item("引信触发阈值", f"{p['bullet_detonator']:.0f}", o, unit="mm")); o += 1
                        if p['bullet_detonator_threshold']: items.append(self.make_item("引信长度", f"{p['bullet_detonator_threshold']:.2f}", o, unit="cal")); o += 1
                        if p['bullet_cap_normalize_max']: items.append(self.make_item("炮弹转正角", f"{p['bullet_cap_normalize_max']:.2f}", o, unit="°")); o += 1
                        rc1 = p['bullet_ricochet_at']
                        rc2 = p['bullet_always_ricochet_at']
                        if rc1 or rc2:
                            items.append(self.make_item("跳弹角度", f"{rc1:.0f}°/{rc2:.0f}°", o)); o += 1
                else:
                    items.append(self.make_item("可用炮弹", acn, o)); o += 1
            # 特殊机制（弹夹/弹鼓炮）
            if drum:
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
        return items

    def _build_atba(self, conn, vc, ship_id, letter, result):
        ammo_map = self.get_name_map("ammo")
        rows = conn.execute(
            "SELECT * FROM ship_module_atba WHERE version_code=? AND ship_id=? AND config_group LIKE ? ORDER BY module_key",
            (vc, ship_id, f"{letter}%")).fetchall()
        if not rows:
            return
        groups = self._group_weapon_rows(conn, vc, ship_id, rows, 'atba', ammo_map)
        items = self._render_weapon_groups(conn, vc, groups, ammo_map)
        if items:
            result[letter] = items

    def _build_secondary_artillery(self, conn, vc, ship_id, letter, result):
        """从 ship_module_secondary_artillery 表构建第二主炮显示数据"""
        ammo_map = self.get_name_map("ammo")
        rows = conn.execute(
            "SELECT * FROM ship_module_secondary_artillery WHERE version_code=? AND ship_id=? AND config_group LIKE ? ORDER BY module_key",
            (vc, ship_id, f"{letter}%")).fetchall()
        if not rows:
            return
        groups = self._group_weapon_rows(conn, vc, ship_id, rows, 'secondary_artillery', ammo_map)
        items = self._render_weapon_groups(conn, vc, groups, ammo_map)
        if items:
            result[letter] = items
            if g['sigma']: items.append(self.make_item("弹着群系数(Sigma)", str(g['sigma']), o)); o += 1
            if g['rotation_speed_h']: items.append(self.make_item("水平回转速度", f"{g['rotation_speed_h']:.1f}", o, unit="°/s")); o += 1
            if g['rotation_speed_v']: items.append(self.make_item("垂直回转速度", f"{g['rotation_speed_v']:.1f}", o, unit="°/s")); o += 1
            # 散步公式
            ir, mr, id_dist = g['ideal_radius'], g['min_radius'], g['ideal_distance']
            if ir and mr and id_dist:
                slope = (ir - mr) / (id_dist / 1000) if id_dist else 0
                intercept = mr * 30
                items.append(self.make_item("横向散步公式", f"{slope:.2f}R + {intercept:.0f}", o)); o += 1
            # 纵向散步
            if g['radius_zero'] is not None and g['radius_max'] is not None:
                r0, rdelim, rmax, delim = g['radius_zero'], g['radius_delim'], g['radius_max'], g['delim']
                pct = f"{delim*100:.0f}%" if delim else "?"
                items.append(self.make_item("纵向散步系数", f"{r0} ~ {rdelim}(R={pct}) ~ {rmax}", o)); o += 1
            seen = set()
            for swp in conn.execute(
                "SELECT DISTINCT ammo_id FROM ship_weapon_projectiles "
                "WHERE version_code=? AND ship_id=? AND module_id=? AND slot_type='secondary_artillery'",
                (vc, ship_id, g['module_key'])).fetchall():
                aid = swp["ammo_id"]
                if aid in seen:
                    continue
                seen.add(aid)
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
                    items.append(self.make_item("可用炮弹", acn, o, row_type="header")); o += 1
                    if p['alpha_damage']: items.append(self.make_item("标伤", f"{p['alpha_damage']:.0f}", o)); o += 1
                    items.append(self.make_item("弹种", p['ammo_type'] or '?', o)); o += 1
                    items.append(self.make_item("炮弹详细属性", "", o, row_type="header")); o += 1
                    if p['explosion_radius']: items.append(self.make_item("炮弹爆炸半径", f"{p['explosion_radius']:.2f}", o, unit="米")); o += 1
                    if p['bullet_diameter']: items.append(self.make_item("炮弹口径", f"{p['bullet_diameter']*1000:.0f}", o, unit="mm")); o += 1
                    if p['bullet_speed']: items.append(self.make_item("炮弹初速", f"{p['bullet_speed']:.0f}", o, unit="m/s")); o += 1
                    if p['bullet_air_drag']: items.append(self.make_item("空阻系数", str(p['bullet_air_drag']), o)); o += 1
                    if p['bullet_mass']: items.append(self.make_item("炮弹重量", f"{p['bullet_mass']:.2f}", o, unit="kg")); o += 1
                    if at == 'HE':
                        if p['burn_prob'] is not None: items.append(self.make_item("起火率", f"{p['burn_prob']*100:.2f}", o, unit="%")); o += 1
                        if p['alpha_piercing_he']: items.append(self.make_item("HE穿深", f"{p['alpha_piercing_he']:.1f}", o, unit="mm")); o += 1
                    elif at == 'SAP':
                        if p['alpha_piercing_cs']: items.append(self.make_item("SAP穿深", f"{p['alpha_piercing_cs']:.1f}", o, unit="mm")); o += 1
                        rc1 = p['bullet_ricochet_at']; rc2 = p['bullet_always_ricochet_at']
                        if rc1 or rc2:
                            items.append(self.make_item("跳弹角度", f"{rc1:.0f}°/{rc2:.0f}°", o)); o += 1
                    elif at == 'AP':
                        if p['bullet_krupp']: items.append(self.make_item("弹头硬度", f"{p['bullet_krupp']:.0f}", o)); o += 1
                        if p['bullet_detonator'] is not None: items.append(self.make_item("引信触发阈值", f"{p['bullet_detonator']:.0f}", o, unit="mm")); o += 1
                        if p['bullet_detonator_threshold']: items.append(self.make_item("引信长度", f"{p['bullet_detonator_threshold']:.2f}", o, unit="cal")); o += 1
                        if p['bullet_cap_normalize_max']: items.append(self.make_item("炮弹转正角", f"{p['bullet_cap_normalize_max']:.2f}", o, unit="°")); o += 1
                        rc1 = p['bullet_ricochet_at']; rc2 = p['bullet_always_ricochet_at']
                        if rc1 or rc2:
                            items.append(self.make_item("跳弹角度", f"{rc1:.0f}°/{rc2:.0f}°", o)); o += 1
                else:
                    items.append(self.make_item("可用炮弹", acn, o)); o += 1
        if items:
            result[letter] = items

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
            if t['reload_time']: items.append(self.make_item("装填时间", str(t['reload_time']), o, unit="秒")); o += 1
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
                    if p['torpedo_speed']: items.append(self.make_item("航速", f"{p['torpedo_speed']:.0f}", o, unit="节")); o += 1
                    dist = p['torpedo_max_dist']
                    if dist: items.append(self.make_item("射程", f"{dist * 0.03:.2f}", o, unit="公里")); o += 1
                    if p['torpedo_visibility']: items.append(self.make_item("被发现距离", f"{p['torpedo_visibility']:.2f}", o, unit="公里")); o += 1
                    if p['torpedo_arming_time']: items.append(self.make_item("鱼雷上浮时间", f"{p['torpedo_arming_time']:.2f}", o, unit="秒")); o += 1
                    if p['flood_generation'] and p['uw_critical']:
                        items.append(self.make_item("基础漏水系数", f"{p['uw_critical']:.2f}", o)); o += 1
                    if is_burn and p['burn_prob']:
                        items.append(self.make_item("基础点火率", f"{p['burn_prob']*100:.0f}", o, unit="%")); o += 1
                    if sge:
                        if sge['search_radius']: items.append(self.make_item("搜索半径", f"{sge['search_radius']:.2f}", o, unit="公里")); o += 1
                        if sge['search_angle']: items.append(self.make_item("搜索角度", f"{sge['search_angle']:.0f}", o, unit="°")); o += 1
                        if sge['max_yaw']: items.append(self.make_item("最大转向角", f"{sge['max_yaw']:.0f}", o, unit="°")); o += 1
                        if sge['max_vertical_speed']: items.append(self.make_item("最大垂直速度", f"{sge['max_vertical_speed']:.2f}", o, unit="节")); o += 1
                        if sge['max_depth_level']: items.append(self.make_item("最大深度级别", f"{sge['max_depth_level']:.0f}", o)); o += 1
                        if sge['target_lost_degradation_time']: items.append(self.make_item("丢失目标降级时间", f"{sge['target_lost_degradation_time']:.1f}", o, unit="秒")); o += 1
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
            if a['aa_gun_name'] and a['aa_gun_name'] not in seen_guns:
                seen_guns.add(a['aa_gun_name'])
                gname = self.resolve_name('gun', a['aa_gun_name']) or a['aa_gun_name']
                gun_list.append(f"{gname} * {a['aa_gun_count']}")
        if any(v is not None for v in auras.values()):
            items.append(self.make_item("持续伤害", "", o, row_type="header")); o += 1
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
                        items.append(self.make_item("射程", f"{min_d:.0f} ~ {max_d:.0f}", o, unit="公里")); o += 1
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
                items.append(self.make_item("射程", f"{bmin:.0f} ~ {bmax:.0f}", o, unit="公里")); o += 1
            bcnt = bubble_data.get("count")
            if bcnt:
                items.append(self.make_item("一次齐射数量", f"{bcnt:.0f}", o)); o += 1
        if gun_list:
            items.append(self.make_item("防空炮", "", o, row_type="header")); o += 1
            for g in gun_list:
                items.append(self.make_item("防空炮名称", g, o)); o += 1
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
            if d['reload_time']: items.append(self.make_item("装填时间", str(d['reload_time']), o, unit="秒")); o += 1
            if d['shot_delay']: items.append(self.make_item("发射间隔", str(d['shot_delay']), o, unit="秒")); o += 1
            if d['max_packs']: items.append(self.make_item("最大组数", str(d['max_packs']), o)); o += 1
            if d['num_shots']: items.append(self.make_item("每组数量", str(d['num_shots']), o)); o += 1
            if d['damage']: items.append(self.make_item("标伤", f"{d['damage']:.0f}", o)); o += 1
            if d['dc_speed']: items.append(self.make_item("下沉速度", f"{d['dc_speed']:.2f}", o, unit="m/s")); o += 1
            if d['dc_timer']: items.append(self.make_item("引信定时", f"{d['dc_timer']:.2f}", o, unit="秒")); o += 1
            if d['dc_max_depth']: items.append(self.make_item("最大深度", f"{d['dc_max_depth']:.0f}", o, unit="米")); o += 1
            if d['depth_splash_size']: items.append(self.make_item("溅射范围", f"{d['depth_splash_size']:.2f}", o, unit="米")); o += 1
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
        items = []
        o = 0
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
            items.append(self.make_item(label, "", o, row_type="header")); o += 1
            for s in group:
                arm = s['armament_name'] or ""
                sname = self.resolve_plane(s['plane_name']) or s['plane_name']
                items.append(self.make_item("飞机型号", sname, o)); o += 1
                if s['charges'] is not None: items.append(self.make_item("最大充能次数", str(s['charges']), o)); o += 1
                if s['reload_time']: items.append(self.make_item("装填时间", str(s['reload_time']), o, unit="秒")); o += 1
                if s['work_time']: items.append(self.make_item("持续时间", str(s['work_time']), o, unit="秒")); o += 1
                mr = s['max_range']
                mir = s.get('min_range')
                def _fmt_range(v):
                    if v is None: return None
                    if v == float('inf'): return "无限"
                    return f"{v/1000:.2f}"
                rtxt = _fmt_range(mr)
                if rtxt: items.append(self.make_item("最大距离", rtxt, o, unit="公里")); o += 1
                rtxt2 = _fmt_range(mir)
                if rtxt2: items.append(self.make_item("最小距离", rtxt2, o, unit="公里")); o += 1
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
                        items.append(self.make_item("巡航速度", str(smwb), o, unit="节")); o += 1
                        if max_mul: items.append(self.make_item("最大速度", f"{smwb * max_mul:.2f}", o, unit="节")); o += 1
                        if min_mul: items.append(self.make_item("最小速度", f"{smwb * min_mul:.2f}", o, unit="节")); o += 1
                    else:
                        if pid.get('max_speed'): items.append(self.make_item("航速", str(pid['max_speed']), o, unit="节")); o += 1
                        if pid.get('cruising_speed'): items.append(self.make_item("巡航速度", str(pid['cruising_speed']), o, unit="节")); o += 1
                    if pid.get('hp'): items.append(self.make_item("单架飞机血量", f"{pid['hp']:.0f}", o)); o += 1
                    if pid.get('flight_height'): items.append(self.make_item("飞行高度", str(pid['flight_height']), o)); o += 1
                    if pid.get('attacker_size'): items.append(self.make_item("攻击编组数量", str(pid['attacker_size']), o)); o += 1
                    if pid.get('visibility_factor') is not None: items.append(self.make_item("被侦测距离", str(pid['visibility_factor']), o, unit="公里")); o += 1
                    # 如果 armament_name 为空，尝试从 plane_basic_info.bomb_name 获取弹药
                    if not arm and pid.get('bomb_name'):
                        arm = pid['bomb_name']
                    if arm and pid.get('attack_count'): items.append(self.make_item("载弹量", str(pid['attack_count']), o)); o += 1
                if arm:
                    pbi = conn.execute(
                        "SELECT species, ammo_type FROM projectile_basic_info WHERE version_code=? AND projectile_id=?",
                        (vc, arm)).fetchone()
                    if pbi:
                        species = pbi['species'] or ""
                        atype = pbi['ammo_type'] or ""
                        items.append(self.make_item(f"── 弹药: {species} ({atype}) ──", "", o, row_type="header")); o += 1
                        _ac = "alpha_damage, bullet_krupp, alpha_piercing_he, alpha_piercing_cs, bullet_speed, explosion_radius, burn_prob, bullet_diameter, bullet_air_drag, bullet_always_ricochet_at, bullet_ricochet_at, bullet_detonator, bullet_detonator_threshold, bullet_cap_normalize_max"
                        _bc = f"damage, skips_json, max_skip_angle, {_ac}"
                        for tbl, cols in [("projectile_bullet_ext", _ac),
                                           ("projectile_bomb_ext", _bc),
                                           ("projectile_rocket_ext", f"damage, {_ac}"),
                                           ("projectile_depth_charge_ext", "damage, dc_speed, dc_timer, dc_max_depth, depth_splash_size")]:
                            ext = conn.execute(f"SELECT {cols} FROM {tbl} WHERE version_code=? AND projectile_id=?", (vc, arm)).fetchone()
                            if ext:
                                if tbl == "projectile_depth_charge_ext":
                                    if ext['damage']: items.append(self.make_item("标伤", f"{ext['damage']:.0f}", o)); o += 1
                                    if ext['dc_speed']: items.append(self.make_item("下沉速度", f"{ext['dc_speed']:.2f}", o, unit="m/s")); o += 1
                                    if ext['dc_timer']: items.append(self.make_item("引信定时", f"{ext['dc_timer']:.2f}", o, unit="秒")); o += 1
                                    if ext['dc_max_depth']: items.append(self.make_item("最大深度", f"{ext['dc_max_depth']:.0f}", o, unit="米")); o += 1
                                    if ext['depth_splash_size']: items.append(self.make_item("溅射范围", f"{ext['depth_splash_size']:.2f}", o, unit="米")); o += 1
                                else:
                                    if ext['alpha_damage']: items.append(self.make_item("标伤", f"{ext['alpha_damage']:.0f}", o)); o += 1
                                    # 穿深/硬度 (inline _append_ammo_pen)
                                    if atype == "HE":
                                        vv = ext['alpha_piercing_he']
                                        if vv: items.append(self.make_item("穿深", f"{vv:.1f}", o, unit="mm")); o += 1
                                    elif atype == "CS":
                                        vv = ext['alpha_piercing_cs']
                                        if vv: items.append(self.make_item("穿深", f"{vv:.1f}", o, unit="mm")); o += 1
                                    else:
                                        vv = ext['bullet_krupp']
                                        if vv: items.append(self.make_item("硬度", f"{vv:.0f}", o)); o += 1
                                    if ext['bullet_speed']: items.append(self.make_item("弹速", f"{ext['bullet_speed']:.0f}", o, unit="m/s")); o += 1
                                    if ext['explosion_radius']: items.append(self.make_item("爆炸半径", f"{ext['explosion_radius']:.2f}", o, unit="米")); o += 1
                                    if ext['burn_prob'] is not None: items.append(self.make_item("起火概率", f"{ext['burn_prob']*100:.2f}", o, unit="%")); o += 1
                                    # AP/CS 专属属性 (inline _append_ammo_extra)
                                    if atype in ("AP", "CS"):
                                        if ext['bullet_air_drag']: items.append(self.make_item("阻力系数", str(ext['bullet_air_drag']), o)); o += 1
                                        if ext['bullet_diameter']: items.append(self.make_item("口径", f"{ext['bullet_diameter']*1000:.2f}", o, unit="mm")); o += 1
                                        if ext['bullet_always_ricochet_at']: items.append(self.make_item("强制跳弹角", f"{ext['bullet_always_ricochet_at']:.0f}", o, unit="°")); o += 1
                                        if ext['bullet_ricochet_at']: items.append(self.make_item("概率跳弹角", f"{ext['bullet_ricochet_at']:.0f}", o, unit="°")); o += 1
                                        if ext['bullet_cap_normalize_max']: items.append(self.make_item("弹头转正角", f"{ext['bullet_cap_normalize_max']:.0f}", o, unit="°")); o += 1
                                        if atype == "AP":
                                            if ext['bullet_detonator']: items.append(self.make_item("引信长度", f"{ext['bullet_detonator']:.0f}", o, unit="秒")); o += 1
                                            if ext['bullet_detonator_threshold']: items.append(self.make_item("引信触发阈值", f"{ext['bullet_detonator_threshold']:.0f}", o, unit="mm")); o += 1
                                break
                        # 跳弹数据（Bomb ext 中）- inline _append_skip_data
                        if ext and tbl == "projectile_bomb_ext":
                            try:
                                import json
                                skips_raw = ext['skips_json']
                                if skips_raw:
                                    skips = json.loads(skips_raw) if isinstance(skips_raw, str) else skips_raw
                                    if isinstance(skips, (list, tuple)):
                                        skip_count = len(skips)
                                        items.append(self.make_item("弹跳次数", f"{skip_count} 次", o)); o += 1
                                        items.append(self.make_item("总共落点段数", f"{skip_count + 1} 段", o)); o += 1
                                    if ext['max_skip_angle']:
                                        items.append(self.make_item("最大弹跳触发角度", f"{ext['max_skip_angle']:.0f}", o, unit="°")); o += 1
                            except Exception:
                                pass
                        # 火箭弹额外读取扫射序列 - inline _append_strafe_time
                        if species == "Rocket":
                            asq = conn.execute(
                                "SELECT attack_sequence_durations FROM projectile_rocket_ext WHERE version_code=? AND projectile_id=?",
                                (vc, arm)).fetchone()
                            if asq and asq['attack_sequence_durations']:
                                try:
                                    seq = json.loads(asq['attack_sequence_durations']) if isinstance(asq['attack_sequence_durations'], str) else asq['attack_sequence_durations']
                                    if isinstance(seq, (list, tuple)) and len(seq) >= 2:
                                        total = sum(seq)
                                        items.append(self.make_item("扫射时间", f"{total:.1f}", o, unit="秒")); o += 1
                                except Exception:
                                    pass
                        else:
                            te = conn.execute(
                                "SELECT alpha_damage, damage, torpedo_speed, torpedo_max_dist, torpedo_visibility, torpedo_arming_time, flood_generation, is_deep_water, deep_water_ignore_classes "
                                "FROM projectile_torpedo_ext WHERE version_code=? AND projectile_id=?",
                                (vc, arm)).fetchone()
                            if te:
                                sge = conn.execute("SELECT max_yaw FROM projectile_torpedo_sub_guidance_ext WHERE version_code=? AND projectile_id=?", (vc, arm)).fetchone()
                                is_guided = sge is not None
                                is_deep = te['is_deep_water']
                                if is_guided: items.append(self.make_item("类型", "声呐导向鱼雷", o)); o += 1
                                elif is_deep: items.append(self.make_item("类型", "深水鱼雷", o)); o += 1
                                ad = te['alpha_damage'] or 0
                                if ad: items.append(self.make_item("标伤", f"{ad * 0.33:.0f}", o)); o += 1
                                if te['torpedo_speed']: items.append(self.make_item("航速", f"{te['torpedo_speed']:.0f}", o, unit="节")); o += 1
                                if te['torpedo_max_dist'] is not None: items.append(self.make_item("最大射程", f"{(te['torpedo_max_dist'] * 30) / 1000:.2f}", o, unit="公里")); o += 1
                                fg = te['flood_generation'] or 0
                                if fg: items.append(self.make_item("基础漏水率", f"{fg * 100:.0f}", o, unit="%")); o += 1
        if items:
            result[letter] = items

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
            # 按 header 行分组：找到 ── X 配置 ── 标记，将后续 items 归入该 letter
            letter_contents: dict[str, list[dict]] = {}
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
            if letter_contents and len(letter_contents) > 1:
                sub_labels = sorted(letter_contents.keys())
                sub_info[label] = {
                    "sub_labels": [f"{l} 配置" for l in sub_labels],
                    "sub_contents": {f"{l} 配置": letter_contents[l] for l in sub_labels},
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
