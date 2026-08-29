"""
ShipPresenter —— 从结构化数据库表组装舰船显示数据（新架构）。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from presenters.wargaming.base import WargamingBasePresenter, NM
from models.name_mapping import Mapping
from services.ballistics_service import BallisticsCalculator
from utils.path_utils import get_data_dir


class WargamingShipPresenter(WargamingBasePresenter):
    """将舰船数据库记录组装为显示结构"""

    #: 炮位安装朝向缓存（ship_id → {hp_key: (yaw, [x,y,z])}），惰性初始化
    _mount_yaw_cache: dict | None = None

    def build(self, ship_id: str, version_code: str = "", modifiers: dict | None = None,
              engine_letter: str = "", fire_control_key: str = "", sonar_key: str = "",
              active_module_keys: dict | None = None) -> dict | None:
        try:
            return self._do_build(ship_id, version_code, modifiers, engine_letter, fire_control_key, sonar_key,
                                  active_module_keys)
        except Exception as e:
            import traceback
            from app.signals import bus
            traceback.print_exc()
            bus.log_message.emit(f"⚠️ [WargamingShipPresenter] {ship_id} 构建失败: {e}")
            return None

    def _get_mod_value(self, mod_val, ship_type: str = "") -> float:
        """从 modifier 值中提取数值，支持 dict 按舰种取值"""
        if isinstance(mod_val, dict):
            if ship_type and ship_type in mod_val:
                return float(mod_val[ship_type])
            # 取第一个非空值
            for v in mod_val.values():
                return float(v)
            return 0.0
        return float(mod_val)

    def _apply_modifiers(self, sections: list[dict], modifiers: dict, section_label: str = "") -> None:
        """将升级品修饰符应用到 section items 的值上"""
        if not modifiers:
            return
        ship_type = getattr(self, '_mod_ship_type', '')
        for section in sections:
            label = section.get("label", "") or section_label
            default_items = section.get("items", [])
            self._apply_modifiers_to_items(default_items, modifiers, label, ship_type)
            # 对多配置 section 的 _items_by_letter 也应用修饰符
            # 注意 section["items"] 与 items_by_letter[首字母] 是同一列表，
            # 因此遍历 _items_by_letter 时需跳过已处理过的首字母
            items_by_letter = section.get("_items_by_letter") or {}
            for letter, letter_items in items_by_letter.items():
                if letter_items is default_items:
                    continue
                self._apply_modifiers_to_items(letter_items, modifiers, label, ship_type)

    def _apply_modifiers_to_items(self, items: list[dict], modifiers: dict, label: str = "",
                                   ship_type: str = "") -> None:
        """将修饰符应用到单组 items 列表"""
        if not items:
            return
        for item in items:
            name = item.get("name", "")
            val_str = item.get("value", "")
            if not val_str:
                continue
            for mod_key, mod_val in modifiers.items():
                # 按前缀限定生效范围：GM=主炮 GS=副炮 GMS=次级主炮
                # 注意 GMShotDelay 也以 GMS 开头，需判断第4个字符是否大写来区分
                is_sub_main = mod_key.startswith("GMS") and len(mod_key) > 3 and mod_key[3].isupper()
                is_main = mod_key.startswith("GM") and not is_sub_main
                is_secondary = mod_key.startswith("GS") and not is_sub_main
                # GMBigGunVisibilityCoeff 作用于船体段隐蔽条目，不受"主炮段"限制
                if is_main and "主炮" not in label and mod_key != "GMBigGunVisibilityCoeff":
                    continue
                if is_secondary and "副炮" not in label:
                    continue
                if is_sub_main and "次级" not in label:
                    continue
                # planeSpeed / diveBomberSpeedMultiplier 影响所有航速相关字段
                if mod_key in ("planeSpeed", "diveBomberSpeedMultiplier") and name in ("航速", "巡航速度", "最大速度", "最小速度"):
                    field = name
                # visibilityDistCoeff 同时影响水面隐蔽和空中隐蔽
                elif mod_key == "visibilityDistCoeff" and name in ("水面隐蔽", "空中隐蔽"):
                    field = name
                # GMBigGunVisibilityCoeff：仅主炮口径≥149mm 的舰船生效（被侦查范围增大）
                elif mod_key == "GMBigGunVisibilityCoeff" and name in ("水面隐蔽", "空中隐蔽"):
                    if not getattr(self, '_big_gun_flag', False):
                        continue
                    field = name
                # GMHeavyCruiserCaliberDamageCoeff：仅主炮口径≥190mm 的舰船生效
                # （重巡 AP 标伤；通过同组"弹种"项判定仅 AP 弹生效，避免误伤 HE/CS 与小口径主炮）
                elif mod_key == "GMHeavyCruiserCaliberDamageCoeff":
                    if not getattr(self, '_heavy_cruiser_flag', False):
                        continue
                    _at = next((i.get("value", "") for i in items if i.get("name") == "弹种"), "")
                    if str(_at).upper() != "AP":
                        continue
                    field = "标伤"
                # planeExtraHangarSize 同时影响最大可用数量和开局可用数量
                elif mod_key == "planeExtraHangarSize" and name in ("最大可用数量", "开局可用数量"):
                    field = name
                # planeAdditionalConsumables 影响"数量"（消耗品次数，加算）
                elif mod_key in ("planeAdditionalConsumables", "additionalConsumables") and name == "数量":
                    field = name
                # healForsageReloadCoeff：仅对引擎加力（healForsage）消耗品的"冷却时间"生效（精确匹配，避免误伤"引擎加速冷却时间"）
                elif mod_key == "healForsageReloadCoeff":
                    if not any(i.get("name") == "类型" and "healForsage" in str(i.get("value", "")) for i in items):
                        continue
                    field = "冷却时间"
                    if field != name.strip():
                        continue
                else:
                    field = Mapping.MODIFIER_FIELD_MAP.get(mod_key)
                if field and (field == name.strip() or name.strip().endswith(field)):
                    try:
                        cur_str = item.get("value", "")
                        if not cur_str:
                            continue
                        # 去除值中嵌入的单位后缀（如 "7 架"、"3架"），之后重新追加
                        import re as _re
                        stripped = _re.sub(r'\s*(架|枚|发|个|次|艘|门|座|组|架次|s|秒)\s*$', '', cur_str)
                        suffix = cur_str[len(stripped):] if len(stripped) < len(cur_str) else ""
                        orig = float(stripped)
                        mv = self._get_mod_value(mod_val, ship_type)
                        # 应用值倍率（如 AABubbleDamageBonus: 42.86 × 7 = 300）
                        factor = Mapping.MODIFIER_VALUE_FACTOR.get(mod_key, 1.0)
                        mv = mv * factor
                        # planeAdditionalConsumables 总是加算
                        if mod_key in ("planeAdditionalConsumables", "additionalConsumables", "crashCrewWorkTimeBonus"):
                            new_val = orig + mv
                        # healthPerLevel / planeHealthPerLevel：每个战舰等级提升的生命值（加算 × 等级）
                        elif mod_key in ("healthPerLevel", "planeHealthPerLevel"):
                            _tier = getattr(self, '_current_tier', 0)
                            new_val = orig + mv * _tier
                        # 乘算系数 (0.5~1.5) vs 加算值
                        elif 0.5 <= mv <= 1.5:
                            new_val = orig * mv
                        else:
                            new_val = orig + mv
                        item["value"] = f"{new_val:.2f}".rstrip("0").rstrip(".") + suffix
                    except (ValueError, TypeError):
                        pass

    def _do_build(self, ship_id: str, version_code: str = "", modifiers: dict | None = None,
                  engine_letter: str = "", fire_control_key: str = "", sonar_key: str = "",
                  active_module_keys: dict | None = None) -> dict | None:
        sections: list[dict] = []
        conn = self.conn
        vc = self._ensure_version(version_code)

        if active_module_keys is None:
            active_module_keys = {}

        # 当未指定引擎/火控时，使用基础（无 prev）配件的模块
        if not engine_letter:
            engine_letter = self._resolve_stock_module_key(conn, vc, ship_id, "_Engine")
        if not fire_control_key:
            fire_control_key = self._resolve_stock_module_key(conn, vc, ship_id, "_Suo")
        if not sonar_key:
            sonar_key = self._resolve_stock_module_key(conn, vc, ship_id, "_Sonar")
        # 为其他模块类型补上 stock key
        _type_to_comp_slot = {
            "_Hull": "hull", "_Artillery": "artillery", "_Torpedoes": "torpedoes",
            "_Sonar": "pinger",
        }
        for ut, slot in _type_to_comp_slot.items():
            if ut not in active_module_keys:
                key = self._resolve_stock_module_key(conn, vc, ship_id, ut)
                if key:
                    active_module_keys[ut] = key

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
        self._append_modules(conn, vc, ship_id, sections, engine_letter, fire_control_key, active_module_keys, sonar_key)

        # ── 5. 应用升级品修饰符 ─────────────────────────
        self._mod_ship_type = basic['shiptype'] or ''
        self._current_tier = basic['tier'] or 0
        # GMBigGunVisibilityCoeff 仅对主炮口径≥149mm 的舰船生效；
        # GMHeavyCruiserCaliberDamageCoeff 仅对主炮口径≥190mm 的舰船生效
        # （口径存于弹药表 bullet_diameter，单位米；经 ship_weapon_projectiles 关联）
        self._big_gun_flag = False
        self._heavy_cruiser_flag = False
        try:
            _cal = conn.execute(
                "SELECT MAX(e.bullet_diameter) AS mc FROM ship_weapon_projectiles p "
                "JOIN projectile_bullet_ext e ON e.version_code=p.version_code "
                "AND e.projectile_id=p.ammo_id "
                "WHERE p.version_code=? AND p.ship_id=? AND p.slot_type='artillery'",
                (vc, ship_id)).fetchone()
            if _cal and _cal['mc'] is not None:
                _cal_mm = float(_cal['mc']) * 1000
                if _cal_mm >= 149.0:
                    self._big_gun_flag = True
                if _cal_mm >= 190.0:
                    self._heavy_cruiser_flag = True
        except Exception:
            pass
        if modifiers:
            for sec in sections:
                self._apply_modifiers([sec], modifiers)
            # 战术机组不享受机库加成：从舰载机段恢复 hangar 原始值
            if "planeExtraHangarSize" in modifiers and self._aircraft_sub_info:
                _has_tactical = any(
                    _cv.get("tactical")
                    for _sv in self._aircraft_sub_info.values()
                    for _tv in _sv.get('sub_contents', {}).values()
                    for _cv in _tv.get('config_contents', {}).values()
                )
                if _has_tactical:
                    for sec in sections:
                        if sec.get("label") == "舰载机":
                            _mv = self._get_mod_value(modifiers["planeExtraHangarSize"])
                            for item in sec.get("items", []):
                                name = item.get("name", "")
                                if name in ("最大可用数量", "开局可用数量"):
                                    vstr = item.get("value", "")
                                    m = __import__('re').match(r'([\d.]+)\s*架', vstr)
                                    if m:
                                        if 0.5 <= _mv <= 1.5:
                                            restored = float(m.group(1)) / _mv
                                        else:
                                            restored = float(m.group(1)) - _mv
                                        item["value"] = f"{restored:.0f} 架"
            # 应用到弹药详情（带 section label 以便 GS 等前缀过滤）
            # GMHeavyCruiserCaliberDamageCoeff 的过滤在 _apply_modifiers_to_items 内完成（参考 GMBigGunVisibilityCoeff）
            for sec in sections:
                sec_label = sec.get("label", "")
                raw_ammo = sec.get("raw_ammo_types", [])
                for a in raw_ammo:
                    self._apply_modifiers([{"items": a.get("detail_items", [])}], modifiers, section_label=sec_label)
            # 应用到飞机子面板（sub_contents → 类型 → config_contents → items + raw_ammo_types）
            # modifier key 前缀 → 飞机类型映射（保证加成只影响对应机种）
            AIRCRAFT_MOD_PREFIX = {
                "diveBomber": "DiveBomber", "bomb": "DiveBomber",
                "torpedoBomber": "TorpedoBomber", "torpedo": "TorpedoBomber",
                "fighter": "Fighter",
                "skipBomber": "SkipBomber",
                "mineBomber": "MineBomber",
            }
            for sk, sv in self._aircraft_sub_info.items():
                sub_keys = sv.get("sub_keys", {})
                # display_name → internal_type, e.g. "轰炸机" → "DiveBomber"
                for type_label, type_val in sv.get('sub_contents', {}).items():
                    ac_type = sub_keys.get(type_label, "")
                    # 过滤 modifier：只保留适用于该机种的 key
                    filtered = {}
                    for mk, mv in modifiers.items():
                        # 无前缀的通用 modifier（如 planeSpeed）全适用
                        if not any(mk.lower().startswith(p.lower()) for p in AIRCRAFT_MOD_PREFIX):
                            filtered[mk] = mv
                        else:
                            # 有前缀的：检查是否匹配当前机种
                            for pref, ptype in AIRCRAFT_MOD_PREFIX.items():
                                if mk.lower().startswith(pref.lower()):
                                    if ac_type == ptype:
                                        filtered[mk] = mv
                                    break
                    if not filtered:
                        continue
                    for ck, cv in type_val.get('config_contents', {}).items():
                        # 战术机组不享受机库加成
                        if cv.get("tactical"):
                            filtered_no_hangar = {k: v for k, v in filtered.items() if k != "planeExtraHangarSize"}
                            if filtered_no_hangar:
                                self._apply_modifiers([{"items": cv.get('items', [])}], filtered_no_hangar)
                                for a in cv.get('raw_ammo_types', []):
                                    self._apply_modifiers([{"items": a.get("detail_items", [])}], filtered_no_hangar)
                                for rc in cv.get('raw_consumables', []):
                                    self._apply_modifiers([{"items": rc.get("detail_items", [])}], filtered_no_hangar)
                        else:
                            self._apply_modifiers([{"items": cv.get('items', [])}], filtered)
                            for a in cv.get('raw_ammo_types', []):
                                self._apply_modifiers([{"items": a.get("detail_items", [])}], filtered)
                            for rc in cv.get('raw_consumables', []):
                                self._apply_modifiers([{"items": rc.get("detail_items", [])}], filtered)

        # ── 6. 构建子 section 信息 ───────────────────────
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
    def _resolve_stock_module_key(conn, vc, ship_id, uc_type: str) -> str:
        """查找指定升级类型的 stock（无 prev）模块的组件 ID"""
        try:
            rows = conn.execute(
                "SELECT components_json FROM ship_upgrade_info "
                "WHERE version_code=? AND ship_id=? AND uc_type=? AND (prev IS NULL OR prev='') "
                "ORDER BY upgrade_key LIMIT 1",
                (vc, ship_id, uc_type)).fetchall()
            if rows:
                comps = json.loads(rows[0]["components_json"] or "{}")
                for mods in comps.values():
                    if mods and mods[0]:
                        return mods[0]
        except Exception:
            pass
        return ""

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
                if v: items.append(self.make_item("弹头硬度", f"{v:.0f}", o)); o += 1
            else:
                v = row['bullet_krupp']
                if v: items.append(self.make_item("穿深", f"{v:.0f}", o)); o += 1
        except (KeyError, IndexError, TypeError):
            pass
        return o

    def _append_ammo_extra(self, items: list, row, ammo_type: str, o: int, max_range_km: float | None = None) -> int:
        """AP/CS/HE 专属属性：弹重、空气阻力系数、口径、跳弹角、引信等，并补充穿深摘要。

        CS(SAP) 与 HE 穿深均为固定值，不显示参与弹道穿深计算的 AP 专属数据（引信、穿深摘要等）。
        弹头硬度已由穿深/硬度行显示，不在此重复。AP 的穿深摘要固定显示在最后一条，
        按出膛/10km/14km/18km 计算，主炮射程不足的预估值不显示。
        """
        if ammo_type not in ("AP", "CS", "HE"):
            return o

        if hasattr(row, 'keys'):
            row = dict(row)

        try:
            if row.get('bullet_mass'):
                items.append(self.make_item("弹重", f"{row['bullet_mass']:.2f}", o, unit="kg")); o += 1
            if row.get('bullet_air_drag'):
                items.append(self.make_item("空气阻力系数", str(row['bullet_air_drag']), o)); o += 1
            if row.get('bullet_diameter'):
                items.append(self.make_item("口径", f"{row['bullet_diameter']*1000:.2f}", o, unit="mm")); o += 1

            if ammo_type in ("AP", "CS"):
                if row.get('bullet_always_ricochet_at'):
                    items.append(self.make_item("强制跳弹角", f"{row['bullet_always_ricochet_at']:.1f}", o, unit="°")); o += 1
                if row.get('bullet_ricochet_at'):
                    items.append(self.make_item("概率跳弹角", f"{row['bullet_ricochet_at']:.1f}", o, unit="°")); o += 1
                if row.get('bullet_cap_normalize_max'):
                    items.append(self.make_item("弹头转正角", f"{row['bullet_cap_normalize_max']:.1f}", o, unit="°")); o += 1

            # AP 专属：引信数据（弹头硬度已由穿深/硬度行显示，不重复）。
            if ammo_type == "AP":
                if row.get('bullet_detonator'):
                    items.append(self.make_item("引信长度", f"{row['bullet_detonator']}", o, unit="s")); o += 1
                if row.get('bullet_detonator_threshold'):
                    items.append(self.make_item("引信触发阈值", f"{row['bullet_detonator_threshold']:.0f}", o, unit="mm")); o += 1

            # AP 穿深摘要：固定显示在最后一条
            if ammo_type == "AP":
                summary = self._build_ap_pen_summary(row, max_range_km)
                if summary:
                    items.append(self.make_item("穿深摘要", summary, o)); o += 1

        except (KeyError, IndexError, TypeError, ValueError):
            pass

        return o

    @staticmethod
    def _build_ap_pen_summary(row, max_range_km: float | None = None) -> str:
        """构建 AP 穿深摘要：出膛/10km/14km/18km（主炮射程不足的距离不显示）。

        使用真实弹道模拟的着速计算绝对穿深，返回多行文本（\n 换行，渲染端支持自动换行）。
        """
        try:
            if hasattr(row, 'keys'):
                row = dict(row)
            mass = float(row.get('bullet_mass') or 0.0)
            caliber = float(row.get('bullet_diameter') or 0.0)
            air_drag = float(row.get('bullet_air_drag') or 0.0)
            velocity = float(row.get('bullet_speed') or 0.0)
            krupp = float(row.get('bullet_krupp') or 0.0)
            if mass <= 0 or caliber <= 0 or air_drag <= 0 or velocity <= 0 or krupp <= 0:
                return ""
            bc = BallisticsCalculator()
            ballistics = bc.calculate_full_ballistics(mass, caliber, air_drag, velocity, krupp)
            lines = []
            for dist_km, label in ((0.0, "出膛"), (10.0, "10km"), (14.0, "14km"), (18.0, "18km")):
                if max_range_km is not None and dist_km > float(max_range_km):
                    continue
                pt = bc.interpolate_at_distance(ballistics, dist_km)
                pen = bc.calc_v3_penetration(krupp, mass, pt["velocity"], caliber)
                lines.append(f"{label} ≈ {pen:.0f}mm")
            return "\n".join(lines)
        except Exception:
            return ""

    @staticmethod
    def format_distance_of_preparation(dop) -> list[str]:
        """解析战术战斗机消耗品特殊词条 distanceOfPreparation 为可读段列表。

        数据结构：[[距离, 准备时间], ...]（WG 数据在 logic 下，入库后随 extra_json
        合并到顶层供显示层读取）。距离 ×0.03 = km（与 workRange 同单位：
        BR_10 的 666.67×0.03=20.00km == 最大攻击距离 20000m），值为该距离下的
        攻击准备时间（秒）。无数据/解析失败返回空列表 []。
        """
        if not dop:
            return []
        segs: list[str] = []
        for pair in dop:
            if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                try:
                    dist_km = float(pair[0]) * 0.03
                    val = pair[1]
                    if not isinstance(val, (int, float)):
                        continue
                    segs.append(f"{dist_km:.2f}km → {val:g}s")
                except (ValueError, TypeError):
                    continue
        return segs

    @staticmethod
    def is_time_based(cfgd: dict) -> bool:
        """时间制消耗品判定：lifeCycleType == 1（以总容量/总时间计数，非次数制）。

        仅限 WG 服模式：本类即 WG presenter；detail_panel 共用入口在调用
        format_time_based 前先用 self.is_wg() 限定，Lesta 不受影响。
        """
        return str(cfgd.get('lifeCycleType', 0)) == '1'

    @staticmethod
    def format_time_based(cfgd: dict) -> list[tuple[str, str]]:
        """生成时间制消耗品特殊显示行 [(标签, 值), ...]（lifeCycleType==1）。

        显示 maxCapacity（最大可用时间）、minWorkTime（最低持续时间）、
        capacityRegenCoeff（可用容量回复率，仅非 0 时显示）。
        非时间制返回空列表 []。
        """
        if not WargamingShipPresenter.is_time_based(cfgd):
            return []
        rows: list[tuple[str, str]] = []
        _cap = cfgd.get('maxCapacity')
        if _cap is not None:
            try:
                _capf = float(_cap)
                if _capf > 0:
                    rows.append(("最大可用时间", f"{_capf:g}s"))
            except (ValueError, TypeError):
                pass
        _mwt = cfgd.get('minWorkTime')
        if _mwt:
            try:
                rows.append(("最低持续时间", f"{float(_mwt):g}s"))
            except (ValueError, TypeError):
                pass
        _crc = cfgd.get('capacityRegenCoeff')
        if _crc is not None:
            try:
                _crcf = float(_crc)
                if _crcf != 0.0:
                    rows.append(("可用容量回复率", f"{_crcf:g}"))
            except (ValueError, TypeError):
                pass
        return rows

    @staticmethod
    def format_aux_torp_buff(conn, vc: str, cfgd: dict) -> list[tuple[str, str, str]]:
        """读取 auxTorpBooster 消耗品引用的 PCOM buff（logic.buff），返回效果词条。"""
        return WargamingShipPresenter.format_pcom_buff(conn, vc, cfgd.get('buff', ''))

    @staticmethod
    def format_torpedo_damage_decrease_buff(conn, vc: str, cfgd: dict) -> list[tuple[str, str, str]]:
        """读取 torpedoDamageDecrease 消耗品引用的 PCOM buff（logic.buff），返回效果词条。"""
        return WargamingShipPresenter.format_pcom_buff(conn, vc, cfgd.get('buff', ''))

    @staticmethod
    def format_pcom_buff(conn, vc: str, buff_id: str) -> list[tuple[str, str, str]]:
        """读取 PCOM 实体（consumable_buff）的 buff 效果词条，返回 [(标签, 格式化值, 颜色), ...]。

        两种入库形态（见 services/wargaming/analysis.py store_consumable_buff）：
          - 扁平 buff（无 level_*，如 PCOM915/916/917 AuxiliaryTorpedoArmamentBooster，
            入库为 buff_level=0 单行）：modifier 子对象即全部有效词条，直接读取。
          - 分级 buff（有 level_N，如 PCOM9xx_AirstrikeCountermeasures*，入库为每级一行，
            buff_json 即该级整份模板）：无 modifier 键，把整个模板当词条源，但只保留
            **有实际效果**的词条——跳过 0 / 1.0 / False 默认值噪音，以及
            GMMaxDistAbsoluteCap / aimRange / healthPerLevel / artilleryBurnChanceBonus /
            BuffStatsList 等常量/元数据噪音键。无数据或全部无效返回 []。
        """
        if not buff_id:
            return []
        try:
            row = conn.execute(
                "SELECT buff_json FROM consumable_buff WHERE version_code=? AND buff_id=? "
                "ORDER BY buff_level LIMIT 1",
                (vc, buff_id)).fetchone()
        except Exception:
            return []
        if not row:
            return []
        try:
            data = json.loads(row['buff_json'] or '{}') or {}
        except (json.JSONDecodeError, TypeError):
            return []
        _flat = data.get('modifier')
        if isinstance(_flat, dict) and _flat:
            # 扁平 buff：modifier 子对象即有效词条（保持原行为）
            mods, strict = _flat, False
        else:
            # 分级 buff：整份 level 模板 → 严格过滤默认值噪音
            mods, strict = data, True
        # 元数据/常量噪音键（分级模板整份入库时会出现）
        SKIP = {
            "id", "index", "type", "name", "descIDs", "titleIDs", "iconIDs",
            "feedbackIDs", "negative", "hidden", "hideLowerLogMessage",
            "restrictions", "opposite", "notificationLevel", "typeinfo",
            "level", "BuffStatsList",
            "aimRange",
        }
        BOOL_GREEN = "#1b8a1b"
        rows: list[tuple[str, str, str]] = []
        for bk, bv in sorted(mods.items()):
            if bk in SKIP or bk.startswith("level_"):
                continue
            if isinstance(bv, bool):
                # 布尔词条：true → 描述文本放右列数据区（绿色），左列留空
                if bv:
                    label = Mapping.MODIFIER_MAP.get(bk, bk)
                    rows.append(("", label, BOOL_GREEN))
                continue
            if isinstance(bv, dict):
                # 分舰种 dict：全 1.0 → 无实际效果；否则取首个非 1.0 值
                nums = [x for x in bv.values() if isinstance(x, (int, float))]
                if not nums or all(abs(x - 1.0) < 1e-9 for x in nums):
                    continue
                bv = next((x for x in nums if abs(x - 1.0) >= 1e-9), 1.0)
            if not isinstance(bv, (int, float)):
                continue
            if abs(bv - 1.0) < 1e-9:
                continue  # coeff 1.0 无效果
            if strict and abs(bv) < 1e-9:
                continue  # 分级模板中 0 = 无效果默认值（raw 加性词条）
            label = Mapping.MODIFIER_MAP.get(bk, bk)
            ft = Mapping.format_modifier(bk, bv)
            if ft:
                rows.append((label, ft, Mapping.get_modifier_color(bk, bv)))
        return rows

    @staticmethod
    def format_support_drop(conn, vc: str, cfgd: dict,
                            resolve_plane=None) -> list[tuple[str, str, str]]:
        """支援飞机投掷类消耗品详情，返回 [(标签, 值, 颜色), ...]。

        适用于 tacticalFireExtinguishing / tacticalBuffHeal /
        tacticalBuffHealConsumableReload（结构相同）。显示：
        部署飞机（logic.planeName）、落地时间（logic.timeFromHeaven）、
        离开时间（logic.flyAwayTime），以及两个 PCOM buff 的效果词条：
        logic.buff（对友军生效）与 logic.buffOnSelf（对自身生效）。
        对友军/对自身为独立分组标题行（右列无信息），其下方每行是各条加成
        （左列=加成标题，右列=数值，参与颜色判定；布尔状态词条描述放右列数据区、绿色）。
        buff 无有效词条时分组行下方回退显示 buff 实体 ID。
        resolve_plane 可选回调：传入解析飞机名（detail_panel 用 bp.resolve_name，
        presenter 用 self.resolve_name）；不传则显示原始 planeName。
        """
        rows: list[tuple[str, str, str]] = []
        pn = cfgd.get('planeName') or ""
        if pn:
            fname = resolve_plane(pn) if resolve_plane else pn
            rows.append(("部署飞机", fname, ""))
        tfh = cfgd.get('timeFromHeaven', 0)
        if tfh:
            rows.append(("落地时间", f"{tfh}s", ""))
        fa = cfgd.get('flyAwayTime', 0)
        if fa:
            rows.append(("离开时间", f"{fa}s", ""))

        def _append_buff_group(label, buff_id):
            # 分组标题行（对友军/对自身，右列无信息）
            # + 各加成独立行：左列=加成标题，右列=数值（参与颜色判定）；布尔状态词条描述放右列数据区+绿色
            rows.append((label, "", ""))
            eff = WargamingShipPresenter.format_pcom_buff(conn, vc, buff_id)
            if eff:
                rows.extend(eff)
            else:
                rows.append(("增益", buff_id, ""))

        buff_id = cfgd.get('buff', '')
        if buff_id:
            _append_buff_group("对友军", buff_id)
        self_id = cfgd.get('buffOnSelf', '')
        if self_id:
            _append_buff_group("对自身", self_id)
        return rows

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
                # WG：效果数据在 logic 子对象，合并到顶层供各类型分支读取
                _logic = cfgd.get('logic')
                if isinstance(_logic, dict):
                    cfgd.update(_logic)
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
                    items.append(self.make_item(f"        冷却时间", f"{cd_time:.0f}", len(items), unit="s"))
                if wt:
                    items.append(self.make_item(f"        持续时间", f"{wt:.0f}", len(items), unit="s"))
                # WG 时间制消耗品（lifeCycleType==1）：以总容量/总时间计数，无次数与固定作用时间
                for _tb_lbl, _tb_val in self.format_time_based(cfgd):
                    items.append(self.make_item(f"        {_tb_lbl}: {_tb_val}", "", len(items)))
                items.append(self.make_item(f"        消耗品效果:", "", len(items)))
                # WG 使用方式（tacticalParams）
                _tp = cfgd.get('tacticalParams') or {}
                if isinstance(_tp, dict) and _tp:
                    _ut = _tp.get('usageType', '')
                    _ut_zh = {"default": "常规", "position": "指定位置", "entity": "指定目标"}.get(_ut, _ut)
                    items.append(self.make_item(f"        使用方式: {_ut_zh}", "", len(items)))
                    _wr = _tp.get('workRange')
                    _ar = _tp.get('aimRange')
                    if _ut == "default":
                        pass
                    else:
                        if _wr:
                            items.append(self.make_item(f"        最大部署距离: {float(_wr)/1000:.2f}km", "", len(items)))
                        elif _ar:
                            items.append(self.make_item(f"        瞄准范围: {float(_ar):.0f}m", "", len(items)))
                # 按类型显示特有属性
                if ct == "crashCrew":
                    items.append(self.make_item(f"          扑灭起火、清除进水、并修复受损配件。", "", len(items)))
                elif ct == "fighter":
                    is_inter = cfgd.get('isInterceptor') or 0
                    items.append(self.make_item(f"          战斗机类型: {'截击机' if is_inter else '战斗机'}", "", len(items)))
                    fn2 = cfgd.get('fightersNum') or 0
                    items.append(self.make_item(f"          飞机数量: {fn2}", "", len(items)))
                    dog = cfgd.get('dogFightTime', 0)
                    if isinstance(dog, dict):
                        dog = next((x for x in dog.values() if isinstance(x, (int, float))), 0)
                    fly = cfgd.get('flyAwayTime', 0)
                    if dog or fly:
                        items.append(self.make_item(f"          狗斗: {dog}s | 离开: {fly}s", "", len(items)))
                    rk = cfgd.get('distanceToKill', 0)
                    if isinstance(rk, dict):
                        rk = next((x for x in rk.values() if isinstance(x, (int, float))), 0)
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
                    # boostCoeff 已是小数加成（0.08 = +8%）；forwardEngineForsag/backwardEngineForsag 为倍率
                    bc = float(cfgd.get('boostCoeff', 0) or 0)
                    items.append(self.make_item(f"          最高航速: {bc*100:+.0f}%", "", len(items)))
                    fef = float(cfgd.get('forwardEngineForsag', 0) or 1)
                    bef = float(cfgd.get('backwardEngineForsag', 0) or 1)
                    items.append(self.make_item(f"          推力: 前进 ×{fef:g} / 后退 ×{bef:g}", "", len(items)))
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
                    hwr = cfgd.get('hydrophoneWaveRadius', 0)
                    if zlt: items.append(self.make_item(f"          虚影存留: {zlt}s", "", len(items)))
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
                    r = float(cfgd.get('radius', 0) or 0)
                    h = cfgd.get('height', 0)
                    lt = cfgd.get('lifeTime', 0)
                    sd = cfgd.get('startDelayTime', 0) or cfgd.get('activationDelay', 0)
                    if r: items.append(self.make_item(f"          烟雾半径: {r*3:.2f}m", "", len(items)))
                    if h: items.append(self.make_item(f"          烟雾高度: {h}m", "", len(items)))
                    if lt: items.append(self.make_item(f"          持续时间: {lt}s", "", len(items)))
                    if sd: items.append(self.make_item(f"          起效延迟: {sd}s", "", len(items)))
                elif ct in ("planeTacticalFighters", "callFighters"):
                    fn = cfgd.get('fightersName') or ""
                    if fn:
                        fname = self.resolve_name('plane', fn) or fn
                        items.append(self.make_item(f"          战斗机名称: {fname}", "", len(items)))
                    tda = cfgd.get('timeDelayAttack', 0)
                    fly = cfgd.get('flyAwayTime', 0)
                    if tda or fly:
                        items.append(self.make_item(f"          攻击延迟: {tda}s | 离开: {fly}s", "", len(items)))
                    wp = cfgd.get('workPreparationTime', 0)
                    if wp:
                        items.append(self.make_item(f"          准备时间: {wp}s", "", len(items)))
                    if ct == "planeTacticalFighters":
                        rd = cfgd.get('radius', 0)
                        items.append(self.make_item(f"          可部署距离: {rd*0.03:.2f}km", "", len(items)))
                        # 特殊词条：准备时间随攻击距离线性变化（distanceOfPreparation）
                        _prep_segs = self.format_distance_of_preparation(
                            cfgd.get('distanceOfPreparation') or [])
                        if _prep_segs:
                            items.append(self.make_item(
                                "          准备时间随距离变化: " + " / ".join(_prep_segs), "", len(items)))
                elif ct == "auxTorpBooster":
                    # 逻辑：为玩家操纵舰船添加 buff（logic.buff → PCOM 实体）
                    for _blbl, _bval, _bcol in self.format_aux_torp_buff(conn, vc, cfgd):
                        # 左列为空（布尔状态词条描述在右列）时只显示值，不带前导冒号
                        _txt = f"{_blbl}: {_bval}" if _blbl else _bval
                        items.append(self.make_item(f"          {_txt}", "", len(items)))
                elif ct in ("tacticalFireExtinguishing", "tacticalBuffHeal",
                            "tacticalBuffHealConsumableReload"):
                    # 支援飞机投掷类：部署飞机/落地时间/离开时间 + logic.buff(buffOnSelf) PCOM buff
                    for _blbl, _bval, _bcol in self.format_support_drop(
                            conn, vc, cfgd, lambda pid: self.resolve_name('plane', pid)):
                        # 分组标题行（对友军/对自身）右列无信息，不带冒号；左列为空行只显示值
                        if _blbl and _bval:
                            _txt = f"{_blbl}: {_bval}"
                        elif _bval:
                            _txt = _bval
                        else:
                            _txt = _blbl
                        items.append(self.make_item(f"          {_txt}", "", len(items)))
                elif ct == "buff":
                    # 逻辑：为玩家操纵舰船添加 buff（logic.buff → PCOM 实体；如 PCY080 反空袭）
                    for _blbl, _bval, _bcol in self.format_torpedo_damage_decrease_buff(conn, vc, cfgd):
                        # 左列为空（布尔状态词条描述在右列）时只显示值，不带前导冒号
                        _txt = f"{_blbl}: {_bval}" if _blbl else _bval
                        items.append(self.make_item(f"          {_txt}", "", len(items)))
        if last_slot is not None:
            items.append(self.make_item(f"      {'─' * 20}", "", len(items)))
        # 收集原始消耗品数据供 UI 构建按钮
        raw_slots: list[dict] = []
        for s in slots:
            _aam, _dam, _ej = [], "", {}
            if conn:
                try:
                    _cfg_r = conn.execute(
                        "SELECT extra_json FROM consumable_configs WHERE version_code=? AND consumable_id=? AND config_key=?",
                        (vc, s['consumable_id'], s['config_key'])).fetchone()
                    if not _cfg_r:
                        _cfg_r = conn.execute(
                            "SELECT extra_json FROM consumable_configs WHERE version_code=? AND consumable_id=? AND config_key='Default'",
                            (vc, s['consumable_id'])).fetchone()
                    if _cfg_r and _cfg_r['extra_json']:
                        _ej = json.loads(_cfg_r['extra_json'])
                        _aam = _ej.get('availableActivationModes') or []
                        _dam = _ej.get('defaultActivationMode') or ""
                except Exception:
                    _aam, _dam, _ej = [], "", {}
            raw_slots.append({
                "slot_index": s['slot_index'],
                "item_index": s['item_index'],
                "consumable_id": s['consumable_id'],
                "config_key": s['config_key'],
                "display_name": self.resolve_name_by_id(
                    s['display_name_id'], 'consumable', s['consumable_id']
                ) or s['consumable_id'] or "",
                "available_activation_modes": _aam,
                "default_activation_mode": _dam,
                "time_based": self.is_time_based(_ej),
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
        # 当前舰船所属舰种（用于分舰种加成按当前舰种唯一显示）
        _basic = conn.execute(
            "SELECT shiptype FROM ship_basic_info WHERE version_code=? AND ship_id=?",
            (vc, ship_id)).fetchone()
        current_species = _basic['shiptype'] if _basic else ""
        items = []
        o = 0
        dname = self.resolve_name_by_id(rage['display_name_id'], 'rage_mode', rage['rage_mode_name']) or "战斗指令"
        # 跳过 === dname === 重复标题
        boost_dur = float(rage['boost_duration'] or 0)
        items.append(self.make_item("持续时间", "即时" if boost_dur == 0 else f"{boost_dur}s", o)); o += 1
        items.append(self.make_item("自动激活", '是' if rage['is_auto_usage'] else '否', o)); o += 1
        items.append(self.make_item("常驻生效", '是' if rage['is_modifier_works_always'] else '否', o)); o += 1

        if rage['decrement_delay']:
            items.append(self.make_item("衰减倒计时", f"{rage['decrement_delay']}s", o)); o += 1
            items.append(self.make_item("衰减周期", f"{rage['decrement_period']}s", o)); o += 1
            items.append(self.make_item("衰减数值", f"{rage['decrement_count']}%", o)); o += 1

        TRIGGER_LABELS = {
            "GameLogicTriggerOnActivation": "触发效果",
            "GameLogicTriggerProgress": "进度积累",
            "GameLogicTrigger": "进度积累",
        }

        def _strip_idx(key):
            # 归一化带数字索引后缀的键（GameLogicTrigger_1 → GameLogicTrigger / Activator_1 → Activator）
            return re.sub(r'_\d+$', '', key)

        triggers = json.loads(rage['triggers_json'] or '[]')
        if triggers:
            for trig_obj in triggers:
                trig_obj = {_strip_idx(k): v for k, v in trig_obj.items()}
                for tkey, tdata in trig_obj.items():
                    tdata = {_strip_idx(k): v for k, v in tdata.items()}
                    trigger_label = TRIGGER_LABELS.get(tkey, tkey)
                    act = tdata.get("Activator", {})
                    atype = act.get("type", "")

                    # 提取所有动作数据
                    actions_found = {k: v for k, v in tdata.items() if k.startswith("Action") and isinstance(v, dict)}

                    if tkey in ("GameLogicTrigger", "GameLogicTriggerProgress") and atype == "RibbonActivator":
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
                    elif atype == "PotentialDamageActivator":
                        pds = act.get("potentialDamageShift", 0)
                        if pds:
                            cond_parts.append(f"承受{pds:.0f}潜在伤害")
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
                                if pn and pn != "default":
                                    effect_parts.append(f"进度: {pn}")
                            else:
                                extra = {k: v for k, v in aln.items() if k != "type"}
                                for ek, ev in extra.items():
                                    label = NM.DETAIL_MAP.get(ek, ek)
                                    effect_parts.append(f"{label}: {ev}")

                    # 从 RageModeProgressAction 提取进度数值
                    progress_val = ""
                    for ak, aln in actions_found.items():
                        if aln.get("type") == "RageModeProgressAction":
                            progress_val = str(aln.get("progress", ""))

                    cond_str = ', '.join(cond_parts) if cond_parts else ""
                    effect_str = '; '.join(effect_parts) if effect_parts else ""

                    if tkey == "GameLogicTriggerOnActivation":
                        if effect_str:
                            items.append(self.make_item(trigger_label, effect_str, o)); o += 1
                    elif tkey in ("GameLogicTriggerProgress", "GameLogicTrigger"):
                        # 进度积累：显示积累条件（每获得xx/承受xx时获得M进度）
                        if cond_str:
                            display = f"每{cond_str}时获得{progress_val}进度" if progress_val else f"每{cond_str}"
                            items.append(self.make_item(trigger_label, display, o)); o += 1
                        elif effect_str:
                            items.append(self.make_item(trigger_label, effect_str, o)); o += 1
                    else:
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
                        if isinstance(mv, dict) and mv and all(k in NM.SHIP_CLASS_MAP for k in mv) \
                                and all(isinstance(v, (int, float)) for v in mv.values()):
                            # 分舰种加成（AAAuraDamage 等）：按当前舰船所属舰种取唯一值显示
                            factor = mv.get(current_species)
                            if factor is None:
                                factor = mv.get("default")
                            if factor is not None:
                                items.append(self.make_item(label, f"{(factor - 1) * 100:+.0f}%", o)); o += 1
                            else:
                                # 当前舰种不在分舰种表中 → 回退列出全部舰种
                                for species_key, f2 in mv.items():
                                    cn = NM.SHIP_CLASS_MAP.get(species_key, species_key)
                                    items.append(self.make_item(f"{label}({cn})", f"{(f2 - 1) * 100:+.0f}%", o)); o += 1
                        elif isinstance(mv, dict):
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

    def _append_modules(self, conn, vc, ship_id, sections, engine_letter="", fire_control_key="",
                        active_module_keys: dict | None = None, sonar_key=""):
        # 获取所有配置组前缀字母
        letters = set()
        for tbl in ["ship_module_hulls", "ship_module_artillery", "ship_module_secondary_artillery",
                      "ship_module_atba",
                      "ship_module_torpedoes", "ship_module_aa", "ship_module_depth_charge",
                      "ship_module_aircraft", "ship_module_air_support", "ship_module_engine",
                      "ship_module_pinger"]:
            for r in conn.execute(
                f"SELECT DISTINCT config_group FROM {tbl} WHERE version_code=? AND ship_id=?",
                (vc, ship_id)).fetchall():
                letters.add(self._config_group_letter(r[0]))
        if not letters:
            return
        letters = sorted(letters)

        # 为每个字母收集各模块数据
        hull_data, arty_data, atba_data, secondary_arty_data, torp_data = {}, {}, {}, {}, {}
        aa_data, dc_data, plane_data, asup_data, pinger_data = {}, {}, {}, {}, {}

        for letter in letters:
            self._build_hull(conn, vc, ship_id, letter, hull_data, engine_letter)
            self._build_artillery(conn, vc, ship_id, letter, arty_data, fire_control_key)
            self._build_atba(conn, vc, ship_id, letter, atba_data)
            self._build_secondary_artillery(conn, vc, ship_id, letter, secondary_arty_data)
            torpedo_key = (active_module_keys or {}).get("_Torpedoes", "")
            self._build_torpedoes(conn, vc, ship_id, letter, torp_data, torpedo_key=torpedo_key)
            self._build_aa(conn, vc, ship_id, letter, aa_data)
            self._build_depth_charge(conn, vc, ship_id, letter, dc_data)
            self._build_air_support(conn, vc, ship_id, letter, asup_data)
            self._build_pinger(conn, vc, ship_id, letter, pinger_data, sonar_key)

        # 先构建引擎卡片数据（用于插入船体卡片下方）
        engine_data: dict[str, list[dict]] = {}
        for letter in letters:
            self._build_engine(conn, vc, ship_id, letter, engine_data, engine_letter)

        for label, data in [("船体", hull_data), ("主炮", arty_data),
                             ("次级主炮", secondary_arty_data), ("副炮", atba_data),
                             ("鱼雷", torp_data), ("防空", aa_data), ("深水炸弹", dc_data),
                             ("声呐", pinger_data)]:
            if data:
                # 只取该 section 实际有数据的配置字母
                section_letters = sorted(data.keys())
                items_by_letter: dict[str, list[dict]] = {}
                ammo_by_letter: dict[str, list[dict]] = {}
                all_ammo: list[dict] = []
                for letter in section_letters:
                    entry = data.get(letter)
                    if not entry:
                        continue
                    # 支持 (items, raw_ammo_types) 元组和纯 items 列表两种格式
                    if isinstance(entry, tuple):
                        letter_items, letter_ammo = entry
                    else:
                        letter_items, letter_ammo = entry, []
                    if letter_items:
                        items_by_letter[letter] = letter_items
                        if letter_ammo:
                            ammo_by_letter[letter] = letter_ammo
                # 默认取第一个字母的 items 和 ammo
                all_items = items_by_letter.get(section_letters[0], []) if section_letters else []
                all_ammo = ammo_by_letter.get(section_letters[0], []) if section_letters else []
                section = self.make_section(label, all_items)
                if len(section_letters) > 1:
                    section["_config_letters"] = section_letters
                    section["_items_by_letter"] = items_by_letter
                    section["_ammo_by_letter"] = ammo_by_letter
                elif all_ammo:
                    section["raw_ammo_types"] = all_ammo
                # 附加炮塔射界入口（在卡片上方显示可点击的射界按钮）
                _slot = {"主炮": "artillery", "副炮": "atba",
                         "次级主炮": "secondary_artillery", "鱼雷": "torpedoes"}.get(label)
                if _slot:
                    _arc_rows = conn.execute(
                        "SELECT hp_key, horiz_sector_json, vert_sector_json, dead_zone_json, pitch_dead_zones_json, position_json "
                        "FROM ship_turret_arcs WHERE version_code=? AND ship_id=? AND slot_type=? "
                        "ORDER BY hp_key", (vc, ship_id, _slot)).fetchall()
                    if _arc_rows:
                        section["_firing_arc"] = self._firing_arc_info(_arc_rows, ship_id, _slot)
                sections.append(section)
                # 引擎卡片紧跟在船体卡片下方
                if label == "船体" and engine_data:
                    e_letters = sorted(engine_data.keys())
                    e_items = {l: engine_data[l] for l in e_letters if engine_data.get(l)}
                    e_all = e_items.get(e_letters[0], []) if e_letters else []
                    e_sec = self.make_section("引擎", e_all)
                    if len(e_letters) > 1:
                        e_sec["_config_letters"] = e_letters
                        e_sec["_items_by_letter"] = e_items
                    sections.append(e_sec)
        # 舰载机独立处理：一个 section + 次级菜单
        plane_section = self._build_aircraft_panel(conn, vc, ship_id, letters, sections)
        if plane_section:
            sections.append(plane_section)
        # 空袭
        if asup_data:
            section_letters = sorted(asup_data.keys())
            items_by_letter: dict[str, list[dict]] = {}
            ammo_by_letter: dict[str, list[dict]] = {}
            for letter in section_letters:
                entry = asup_data.get(letter, {})
                if not entry:
                    continue
                letter_items = entry.get("items", [])
                letter_ammo_batch = entry.get("raw_ammo_types", [])
                if letter_items:
                    items_by_letter[letter] = letter_items
                    if letter_ammo_batch:
                        ammo_by_letter[letter] = letter_ammo_batch
            if items_by_letter:
                all_items = items_by_letter.get(section_letters[0], [])
                section = self.make_section("支援", all_items)
                if len(section_letters) > 1:
                    section["_config_letters"] = section_letters
                    section["_items_by_letter"] = items_by_letter
                    section["_ammo_by_letter"] = ammo_by_letter
                elif ammo_by_letter:
                    section["raw_ammo_types"] = ammo_by_letter.get(section_letters[0], [])
                sections.append(section)

    def _firing_arc_info(self, rows, ship_id: str, slot_type: str) -> dict:
        """从 ship_turret_arcs 行生成射界信息（供详情面板按钮显示）。

        含齐射角：全炮塔能齐射时为前/后（X°（前）/Y°（后））；
        炮塔分列左右舷、无法全炮塔齐射时为左舷/右舷（X°（左舷）/Y°（右舷））。

        炮位安装朝向/位置（mount_yaw/mount_pos）**直接从 assets_data.db** 读取
        （HP_ 挂点解码值），不再依赖回填到 game_data.db ship_turret_arcs 的值。
        """
        import json as _json
        from utils.firing_arc import firing_arc_angles

        mount_map = self._ship_mount_yaw_map(ship_id)
        guns = []
        for r in rows:
            try:
                hp = r["hp_key"]
                myaw, mpos = mount_map.get(hp, (None, None))
                guns.append({
                    "horiz_sector": _json.loads(r["horiz_sector_json"]) if r["horiz_sector_json"] else None,
                    "vert_sector": _json.loads(r["vert_sector_json"]) if r["vert_sector_json"] else None,
                    "dead_zones": _json.loads(r["dead_zone_json"]) if r["dead_zone_json"] else [],
                    "pitch_dead_zones": _json.loads(r["pitch_dead_zones_json"]) if r["pitch_dead_zones_json"] else [],
                    "position": _json.loads(r["position_json"]) if r["position_json"] else None,
                    "mount_yaw": myaw,
                    "mount_pos": mpos,
                })
            except Exception:
                continue
        result = firing_arc_angles(guns)
        result.update({"ship_id": ship_id, "slot_type": slot_type, "count": len(rows)})
        return result

    def _ship_mount_yaw_map(self, ship_id: str) -> dict:
        """直接从 assets_data.db 读该船炮位安装朝向：{hp_key: (yaw, [x,y,z])}。

        数据源：assets_data.db 的 skeleton_mounts（HP_ 挂点解码值，加载数据时预提取）。
        按 ship_id 缓存（姊妹舰/共享船体复用）。无数据（未加载数据）返回 {}，
        射界功能回退到默认朝向。
        """
        if self._mount_yaw_cache is None:
            self._mount_yaw_cache = {}
        cached = self._mount_yaw_cache.get(ship_id)
        if cached is not None:
            return cached
        out: dict = {}
        try:
            import math
            from services.assets_cache_service import AssetsCacheService
            from app.application import app as app_ctx
            row = self.conn.execute(
                "SELECT model_folder FROM ship_models WHERE ship_id=? LIMIT 1",
                (ship_id,)).fetchone()
            stem = ""
            if row:
                try:
                    stem = row["model_folder"] or ""
                except (IndexError, TypeError, KeyError):
                    stem = row[0] or ""
            if stem:
                c = AssetsCacheService()
                mounts = c.get_skeleton_mounts(app_ctx.ctx.bin_folder or "", stem)
                for hp, m in mounts.items():
                    yaw = math.degrees(math.atan2(m[0, 2], m[2, 2])) % 360.0
                    out[hp] = (round(yaw, 1),
                               [round(m[0, 3], 4), round(m[1, 3], 4), round(m[2, 3], 4)])
        except Exception:
            out = {}
        self._mount_yaw_cache[ship_id] = out
        return out

    # ── 模块构建子方法 ─────────────────────────────────────

    def _build_hull(self, conn, vc, ship_id, letter, result, engine_letter=""):
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
                ("turning_radius", "转弯半径", "m"),
                ("rudder_time", "转舵时间", "s"),
            ]:
                val = h[col]
                if val is not None:
                    details = []
                    if col == "health":
                        # 基础血量 tooltip: 吃水深度 + 舰船尺寸
                        if h['draft'] is not None:
                            details.append({"name": "吃水深度", "value": f"{h['draft']:.1f}", "unit": "m"})
                        if h['length'] is not None:
                            details.append({"name": "舰长", "value": f"{h['length']:.1f}", "unit": "m"})
                        if h['width'] is not None:
                            details.append({"name": "舰宽", "value": f"{h['width']:.1f}", "unit": "m"})
                        if h['height'] is not None:
                            details.append({"name": "舰高", "value": f"{h['height']:.1f}", "unit": "m"})
                    items.append(self.make_item(label, f"{val:.0f}" if col == "health" else f"{val:.2f}", o, unit=unit, details=details or None))
                    o += 1
            # 舰船三围（舰长/舰宽/舰高）作为独立行直接显示
            for col, label, unit in [
                ("length", "舰长", "m"),
                ("width", "舰宽", "m"),
                ("height", "舰高", "m"),
                ("draft", "吃水深度", "m"),
            ]:
                v = h[col]
                if v is not None:
                    items.append(self.make_item(label, f"{v:.1f}", o, unit=unit)); o += 1
            # 鱼雷防护 PTZ = (1 - 进水概率 × 3) × 100%
            if h['flood_prob'] is not None:
                ptz = (1.0 - h['flood_prob'] * 3.0) * 100
                items.append(self.make_item("鱼雷防护。减少伤害", f"{ptz:.0f}", o, unit="%")); o += 1

            # 起火/进水持续时间（字段名与 MODIFIER_MAP 匹配以便修饰符生效）
            if h['fire_duration'] is not None:
                items.append(self.make_item("灭火时间", f"{h['fire_duration']:.0f}", o, unit="s")); o += 1
            if h['flood_duration'] is not None:
                items.append(self.make_item("进水恢复时间", f"{h['flood_duration']:.0f}", o, unit="s")); o += 1
            # 被点火概率（字段名与 MODIFIER_MAP 匹配以便修饰符生效）→ 放入 tooltip
            fire_prob_str = None
            if h['fire_prob'] is not None:
                fire_prob_str = f"{h['fire_prob']*100:.2f}"
            # 每秒灼烧/进水损失血量 (值=百分比,×血量得实际值)
            if h['fire_dps'] is not None:
                dps = round(h['fire_dps'] / 100 * h['health'])
                details = []
                if fire_prob_str is not None:
                    details.append({"name": "起火的风险", "value": fire_prob_str, "unit": "%"})
                items.append(self.make_item("每秒灼烧血量", f"{dps}", o, unit="", details=details or None)); o += 1
            if h['flood_dps'] is not None:
                dps = round(h['flood_dps'] / 100 * h['health'])
                items.append(self.make_item("每秒进水量", f"{dps}", o, unit="")); o += 1

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
                # 主要参数作为单独行显示
                for col, label, unit in [
                    ("battery_capacity", "电池容量", ""),
                    ("battery_regen", "电力恢复", "/s"),
                    ("hydrophone_radius", "水听器工作半径", "km"),
                    ("buoyancy_rudder_time", "水平舵转舵时间", "s"),
                ]:
                    v = ext[col]
                    if v is not None:
                        items.append(self.make_item(label, f"{v:.2f}" if isinstance(v, float) else str(v), o, unit=unit))
                        o += 1

                # 其余参数收进 tooltip
                sub_details = []
                for col, label, unit in [
                    ("hydrophone_update_freq", "水听器更新周期", "s"),
                    ("max_buoyancy_speed", "最大上浮/下潜速度", "kts"),
                ]:
                    v = ext[col]
                    if v is not None:
                        sub_details.append(self.make_item(label, f"{v:.2f}" if isinstance(v, float) else str(v), len(sub_details), unit=unit))

                # 深度状态：计算实际航速 = 基础最大航速 × 系数
                base_speed = h['max_speed']
                for ds in conn.execute(
                    "SELECT * FROM ship_sub_depth_states WHERE version_code=? AND ship_id=? AND config_group=? AND module_key=?",
                    (vc, ship_id, h['config_group'], h['module_key'])).fetchall():
                    cn_name = NM.DEPTH_MAP.get(ds['state_name'], ds['state_name'])
                    speed_val = base_speed * ds['underwater_max_speed']
                    depth_val = f"{speed_val:.1f}"
                    if ds['visibility_factor'] is not None:
                        depth_val += f"（隐蔽×{ds['visibility_factor']}）"
                    sub_details.append(self.make_item(f"{cn_name}航速", depth_val, len(sub_details), unit="kts"))

                if sub_details:
                    items.append(self.make_item("潜艇详细性能", "查看详情", o, details=sub_details))
                    o += 1

        if items:
            result[letter] = items

    def _build_engine(self, conn, vc, ship_id, letter, result, engine_letter=""):
        """构建引擎独立卡片：马力、最大航速、弹射起步、全功率加速时间、进水惩罚"""
        items: list[dict] = []
        o = 0
        eng_row = None
        if engine_letter:
            eng_row = conn.execute(
                "SELECT * FROM ship_module_engine WHERE version_code=? AND ship_id=? AND module_key=?",
                (vc, ship_id, engine_letter)).fetchone()
        if not eng_row:
            eng_row = conn.execute(
                "SELECT * FROM ship_module_engine WHERE version_code=? AND ship_id=? ORDER BY module_key LIMIT 1",
                (vc, ship_id)).fetchone()
        if not eng_row:
            return
        # 船体基础航速（用于 speedCoef 修正显示）
        base_speed = None
        hrow = conn.execute(
            "SELECT max_speed, tonnage FROM ship_module_hulls WHERE version_code=? AND ship_id=? AND config_group LIKE ? ORDER BY module_key LIMIT 1",
            (vc, ship_id, f"{letter}%")).fetchone()
        if hrow:
            base_speed = hrow['max_speed']

        if eng_row['engine_power'] is not None:
            items.append(self.make_item("引擎马力", f"{eng_row['engine_power']:.0f}", o, unit="HP")); o += 1
        # 推重比 = 引擎马力 / 排水量
        tonnage = hrow['tonnage'] if hrow is not None else None
        if eng_row['engine_power'] is not None and tonnage:
            items.append(self.make_item("推重比", f"{eng_row['engine_power'] / tonnage:.2f}", o, unit="")); o += 1
        # 最大航速：speedCoef != 0 时用船体基础航速×(1+speedCoef)，否则用船体基础航速
        cur_max_speed = None
        if base_speed is not None:
            sc = eng_row['speed_coef']
            if sc is not None and sc != 0:
                cur_max_speed = base_speed * (1 + sc)
                items.append(self.make_item("最大航速", f"{cur_max_speed:.2f}", o, unit="kts",
                    details=[{"name": "基础航速", "value": f"{base_speed:.2f}", "unit": "kts"}])); o += 1
            else:
                cur_max_speed = base_speed
                items.append(self.make_item("最大航速", f"{cur_max_speed:.2f}", o, unit="kts")); o += 1
        elif eng_row['forward_max_speed'] is not None:
            cur_max_speed = eng_row['forward_max_speed']
            items.append(self.make_item("最大航速", f"{cur_max_speed:.2f}", o, unit="kts")); o += 1
        # 弹射起步航速（前进）：forwardEngineForsag == 1.75 时视为拥有弹射起步
        ffp = eng_row['forward_forsage_power']
        ffms = eng_row['forward_forsage_max_speed']
        if ffp is not None and abs(float(ffp) - 1.75) < 1e-9 and ffms is not None:
            items.append(self.make_item("弹射起步航速", f"{ffms:.1f}", o, unit="kts")); o += 1
        # 弹射起步航速（后退）
        bfms = eng_row['backward_forsage_max_speed']
        if bfms is not None and bfms > 5:
            items.append(self.make_item("弹射起步航速(后退)", f"{bfms:.1f}", o, unit="kts")); o += 1
        # 全功率加速时间
        fut = eng_row['forward_engine_up_time']
        if fut is not None:
            items.append(self.make_item("前进时达到引擎全功率所需加速时间", f"{fut:.1f}", o, unit="s")); o += 1
        but_ = eng_row['backward_engine_up_time']
        if but_ is not None:
            items.append(self.make_item("后退时达到引擎全功率所需加速时间", f"{but_:.1f}", o, unit="s")); o += 1
        # 进水时航速（计算后的实际航速 = 当前最大航速 × (1 + 惩罚系数)）
        fwd = eng_row['forward_speed_on_flood']
        bwd = eng_row['backward_speed_on_flood']
        if fwd is not None and cur_max_speed is not None:
            items.append(self.make_item("进水时前进速度", f"{cur_max_speed * (1 + fwd):.2f}", o, unit="kts")); o += 1
        if bwd is not None and cur_max_speed is not None:
            items.append(self.make_item("进水时后退速度", f"{cur_max_speed * (1 + bwd):.2f}", o, unit="kts")); o += 1

        if items:
            result[letter] = items

    def _build_artillery(self, conn, vc, ship_id, letter, result, fire_control_key=""):
        """构建主炮数据（按 _build_hull 风格：直接 DB 查询 → kv 条目）"""
        ammo_map = self.get_name_map("ammo")
        rows = conn.execute(
            "SELECT * FROM ship_module_artillery WHERE version_code=? AND ship_id=? AND config_group LIKE ? ORDER BY module_key",
            (vc, ship_id, f"{letter}%")).fetchall()
        if not rows:
            return
        items = []
        raw_ammo_types: list[dict] = []
        o = 0
        for gi, g_row in enumerate(rows):
            if gi > 0:
                items.append({"row_type": "separator", "name": "", "value": "", "order": o}); o += 1
            g = dict(g_row)
            gname = self.resolve_name('gun', g.get('launcher_name') or g['module_key']) or g['module_key']
            # 查询火控系数
            fc = None
            if fire_control_key:
                fc = conn.execute(
                    "SELECT max_dist_coef, sigma_count_coef FROM ship_module_fire_control WHERE version_code=? AND ship_id=? AND module_key=?",
                    (vc, ship_id, fire_control_key)).fetchone()
            items.append(self.make_item("炮塔", f"{gname} {g['count']:.0f}×{g['num_barrels']:.0f}", o)); o += 1
            if g['reload_time']: items.append(self.make_item("装填时间", str(g['reload_time']), o, unit="s")); o += 1
            # 射程 × maxDistCoef
            base_range = g['max_range']
            disp_range = base_range
            if base_range:
                if fc and fc['max_dist_coef'] is not None and fc['max_dist_coef'] != 1.0:
                    disp_range = base_range * fc['max_dist_coef']
                    items.append(self.make_item("最大射程", f"{disp_range:.2f}", o, unit="km",
                        details=[{"name": "基础射程", "value": f"{base_range:.2f}", "unit": "km"}])); o += 1
                else:
                    items.append(self.make_item("最大射程", f"{base_range:.2f}", o, unit="km")); o += 1
            # 散步公式
            ir, mr, id_dist = g['ideal_radius'], g['min_radius'], g['ideal_distance']
            if ir and mr and id_dist:
                slope = (ir - mr) / (id_dist / 1000) if id_dist else 0
                intercept = mr * 30
                items.append(self.make_item("横向散步公式", f"{slope:.2f}R + {intercept:.0f}", o)); o += 1
            if g.get('radius_zero') is not None and g.get('radius_max') is not None:
                r0, rdelim, rmax, delim = g.get('radius_zero'), g.get('radius_delim'), g.get('radius_max'), g.get('delim')
                pct = f"{delim*100:.0f}%" if delim else "?"
                items.append(self.make_item("纵向散步系数", f"{r0} ~ {rdelim}(R={pct}) ~ {rmax}", o)); o += 1
            # Sigma × sigmaCountCoef
            base_sigma = g['sigma']
            if base_sigma:
                disp_sigma = base_sigma
                if fc and fc['sigma_count_coef'] is not None and fc['sigma_count_coef'] != 1.0:
                    disp_sigma = base_sigma * fc['sigma_count_coef']
                    items.append(self.make_item("弹着群系数(Sigma)", f"{disp_sigma:.1f}", o,
                        details=[{"name": "基础Sigma", "value": f"{base_sigma:.1f}"}])); o += 1
                else:
                    items.append(self.make_item("弹着群系数(Sigma)", str(base_sigma), o)); o += 1
            if g.get('rotation_speed_h') is not None:
                items.append(self.make_item("水平回转速度", f"{g['rotation_speed_h']:.1f}", o, unit="°/s")); o += 1
                rot_180 = 180.0 / g['rotation_speed_h']
                items.append(self.make_item("180°回转时间", f"{rot_180:.1f}", o, unit="s")); o += 1
            if g.get('rotation_speed_v') is not None: items.append(self.make_item("垂直回转速度", f"{g['rotation_speed_v']:.1f}", o, unit="°/s")); o += 1
            if g.get('caliber') is not None: items.append(self.make_item("口径", f"{g['caliber']*1000:.0f}", o, unit="mm")); o += 1
            # 弹药（按 HE→SAP→AP 顺序）
            ammo_ids = self._sort_ammo_ids(conn, vc, [
                r["ammo_id"] for r in conn.execute(
                    "SELECT DISTINCT ammo_id FROM ship_weapon_projectiles WHERE version_code=? AND ship_id=? AND module_id=? AND slot_type=?",
                    (vc, ship_id, g['module_key'], 'artillery')).fetchall()
            ])
            for aid in ammo_ids:
                aname = ammo_map.get(aid.upper(), self.resolve_name('ammo', aid) or aid)
                items.append(self.make_item("弹药", aname, o)); o += 1
                # 收集弹药详情（供选用）
                p = conn.execute("SELECT species, ammo_type FROM projectile_basic_info WHERE version_code=? AND projectile_id=?", (vc, aid)).fetchone()
                if p:
                    sp = (p['species'] or "").lower()
                    at = (p['ammo_type'] or "").upper()
                    detail_items: list[dict] = []
                    di = 0
                    be = conn.execute("SELECT alpha_damage, bullet_krupp, alpha_piercing_he, alpha_piercing_cs, bullet_speed, explosion_radius, burn_prob, bullet_mass, bullet_diameter, bullet_air_drag, bullet_always_ricochet_at, bullet_ricochet_at, bullet_detonator, bullet_detonator_threshold, bullet_cap_normalize_max FROM projectile_bullet_ext WHERE version_code=? AND projectile_id=?", (vc, aid)).fetchone()
                    if be:
                        if be['alpha_damage']: detail_items.append(self.make_item("标伤", f"{be['alpha_damage']:.0f}", di)); di += 1
                        detail_items.append(self.make_item("弹种", at, di)); di += 1
                        di = self._append_ammo_pen(detail_items, be, at, di)
                        if be['bullet_speed']: detail_items.append(self.make_item("弹速", f"{be['bullet_speed']:.0f}", di, unit="m/s")); di += 1
                        if be['burn_prob'] is not None and at == "HE": detail_items.append(self.make_item("起火概率", f"{be['burn_prob']*100:.2f}", di, unit="%")); di += 1
                        di = self._append_ammo_extra(detail_items, be, at, di, max_range_km=disp_range or None)
                    raw_ammo_types.append({"ammo_id": aid, "name": aname, "species": sp, "ammo_type": at, "detail_items": detail_items})
            # 特殊机制
            ext = conn.execute(
                "SELECT * FROM ship_module_artillery_ext WHERE version_code=? AND ship_id=? AND config_group=? AND module_key=?",
                (vc, ship_id, g['config_group'], g['module_key'])).fetchone()
            if ext:
                ext = dict(ext)
                # 弹夹/弹鼓炮
                if ext.get('special_mode_name'):
                    items, o = self._append_switchable_wg(ext, items, o, conn=conn, vc=vc, ammo_map=ammo_map, raw_ammo_types=raw_ammo_types, disp_range=disp_range)
                # 通用特殊属性
                for col, label, unit in [("rate_of_fire_boost", "射速提升", "%"), ("range_boost", "射程提升", "%")]:
                    if ext.get(col) is not None:
                        items.append(self.make_item(label, f"{ext[col]:.1f}", o, unit=unit)); o += 1
        if items:
            result[letter] = (items, raw_ammo_types)

    def _group_weapon_rows(self, conn, vc, ship_id, rows, slot_type, ammo_map):
        """按炮塔属性分组同一模块下的相同武器"""
        groups: list[dict] = []
        for g_row in rows:
            g = dict(g_row)  # sqlite3.Row → dict
            # 取该武器可用的弹药 ID 列表（按 HE→SAP→AP 顺序）
            ammo_ids = self._sort_ammo_ids(conn, vc, [
                r["ammo_id"] for r in conn.execute(
                    "SELECT DISTINCT ammo_id FROM ship_weapon_projectiles "
                    "WHERE version_code=? AND ship_id=? AND module_id=? AND slot_type=?",
                    (vc, ship_id, g['module_key'], slot_type)).fetchall()
            ])
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
        相同炮塔的组会自动合并属性（不同值用 / 分隔，相同值只显示一次）。"""
        items = []
        raw_ammo_types: list[dict] = []
        # 按炮塔分组
        name_groups: dict[str, list[dict]] = {}
        for grp in groups:
            gname = self.resolve_name('gun', grp["row"].get('launcher_name') or grp["row"]['module_key']) or grp["row"]['module_key']
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
        gname = self.resolve_name('gun', g.get('launcher_name') or g['module_key']) or g['module_key']
        items.append(self.make_item("炮塔", f"{gname} {total_count}×{g['num_barrels']:.0f}", o)); o += 1
        if g['reload_time']: items.append(self.make_item("装填时间", str(g['reload_time']), o, unit="s")); o += 1
        items, o = self._append_weapon_common(conn, vc, g, items, o)
        raw_ammo = self._collect_ammo_types(conn, vc, ammo_ids, ammo_map)
        for a in raw_ammo:
            items.append(self.make_item("弹药", a["name"], o)); o += 1
        items, o = self._append_switchable_wg(drum, items, o, conn=conn, vc=vc, ammo_map=ammo_map, raw_ammo_types=raw_ammo)
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

        gname = self.resolve_name('gun', g0.get('launcher_name') or g0['module_key']) or g0['module_key']
        barrel_vals = all_vals.get('num_barrels', [])
        if barrel_vals:
            barrel_display = f"{barrel_vals[0]:.0f}" if len(set(barrel_vals)) == 1 else "/".join(f"{v:.0f}" for v in barrel_vals)
            items.append(self.make_item("炮塔", f"{gname} {total_count}×{barrel_display}", o)); o += 1
        else:
            items.append(self.make_item("炮塔", f"{gname} {total_count}×1", o)); o += 1
        reload_vals = all_vals.get('reload_time', [])
        if reload_vals:
            display = f"{reload_vals[0]} s" if len(set(reload_vals)) == 1 else " / ".join(f"{v} s" for v in reload_vals)
            items.append(self.make_item("装填时间", display, o)); o += 1

        items, o = self._append_weapon_common(conn, vc, g0, items, o)
        raw_ammo = self._collect_ammo_types(conn, vc, self._sort_ammo_ids(conn, vc, list(all_ammo_ids)), ammo_map)
        for a in raw_ammo:
            items.append(self.make_item("弹药", a["name"], o)); o += 1

        if all_drums:
            items, o = self._append_switchable_wg(all_drums[0], items, o, conn=conn, vc=vc, ammo_map=ammo_map, raw_ammo_types=raw_ammo)
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
        if g.get('rotation_speed_h'):
            items.append(self.make_item("水平回转速度", f"{g['rotation_speed_h']:.1f}", o, unit="°/s")); o += 1
            rot_180 = 180.0 / g['rotation_speed_h']
            items.append(self.make_item("180°回转时间", f"{rot_180:.1f}", o, unit="s")); o += 1
        if g.get('rotation_speed_v'): items.append(self.make_item("垂直回转速度", f"{g['rotation_speed_v']:.1f}", o, unit="°/s")); o += 1
        if g.get('caliber'): items.append(self.make_item("口径", f"{g['caliber']*1000:.0f}", o, unit="mm")); o += 1
        return items, o

    def _sort_ammo_ids(self, conn, vc, ammo_ids):
        """弹药显示顺序：HE → SAP(CS) → AP → 鱼雷 → 深弹；其余类型保持编号顺序"""
        if not ammo_ids:
            return list(ammo_ids)
        key_map = {str(aid): (5, str(aid)) for aid in ammo_ids}
        placeholders = ",".join("?" * len(ammo_ids))
        try:
            rows = conn.execute(
                f"SELECT projectile_id, species, ammo_type FROM projectile_basic_info "
                f"WHERE version_code=? AND projectile_id IN ({placeholders})",
                (vc, *ammo_ids)).fetchall()
            for r in rows:
                sp = (r['species'] or "").lower()
                at = (r['ammo_type'] or "").upper()
                aid = str(r['projectile_id'])
                if "depthcharge" in sp:
                    key = 4
                elif "torpedo" in sp:
                    key = 3
                elif at == "HE":
                    key = 0
                elif at in ("CS", "SAP"):
                    key = 1
                elif at == "AP":
                    key = 2
                else:
                    key = 5
                key_map[aid] = (key, aid)
        except Exception:
            pass
        return sorted(ammo_ids, key=lambda aid: key_map.get(str(aid), (5, str(aid))))

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
        elif at == 'CS':
            if p['alpha_piercing_cs']: detail_items.append(self.make_item("SAP穿深", f"{p['alpha_piercing_cs']:.1f}", di, unit="mm")); di += 1
            rc1 = p['bullet_ricochet_at']; rc2 = p['bullet_always_ricochet_at']
            if rc1 or rc2:
                detail_items.append(self.make_item("跳弹角度", f"{rc1:.1f}°/{rc2:.1f}°", di)); di += 1
        elif at == 'AP':
            if p['bullet_krupp']: detail_items.append(self.make_item("弹头硬度", f"{p['bullet_krupp']:.0f}", di)); di += 1
            if p['bullet_detonator'] is not None: detail_items.append(self.make_item("引信触发阈值", f"{p['bullet_detonator']:.2f}", di, unit="mm")); di += 1
            if p['bullet_detonator_threshold']: detail_items.append(self.make_item("引信长度", f"{p['bullet_detonator_threshold']}", di, unit="")); di += 1
            if p['bullet_cap_normalize_max']: detail_items.append(self.make_item("炮弹转正角", f"{p['bullet_cap_normalize_max']:.2f}", di, unit="°")); di += 1
            rc1 = p['bullet_ricochet_at']; rc2 = p['bullet_always_ricochet_at']
            if rc1 or rc2:
                detail_items.append(self.make_item("跳弹角度", f"{rc1:.1f}°/{rc2:.1f}°", di)); di += 1
        if p['bullet_speed']: detail_items.append(self.make_item("弹速", f"{p['bullet_speed']:.2f}", di, unit="m/s")); di += 1
        if p['bullet_mass']: detail_items.append(self.make_item("弹重", f"{p['bullet_mass']:.2f}", di, unit="kg")); di += 1
        return detail_items


    def _append_switchable_wg(self, drum, items, o, conn=None, vc="", ammo_map=None, raw_ammo_types=None, disp_range=None):
        """WG：替代射击/连发射击模式（ship_module_artillery_ext 的 switchablemode_* 列）"""
        if not drum:
            return items, o
        sc = drum.get('switchablemode_shots_count') or 0
        sd = drum.get('switchablemode_shot_delay')
        frt = drum.get('switchablemode_full_reload_time')
        mode_name = drum.get('special_mode_name') or "连发射击-替代射击模式"
        items.append(self.make_item(mode_name, "", o, row_type="sub_header")); o += 1
        if sc > 1:
            items.append(self.make_item("连发轮数", f"{sc:.0f}", o)); o += 1
        if sd:
            items.append(self.make_item("连发间隔", f"{sd}s", o)); o += 1
        if frt:
            items.append(self.make_item("长装填时间", f"{frt}s", o)); o += 1
        # WG 特有：可切换副弹药 —— 与常规弹药一致的卡片形式
        sec_raw = drum.get('switchablemode_secondary_ammo_list')
        if sec_raw and raw_ammo_types is not None:
            try:
                sec_list = json.loads(sec_raw) if isinstance(sec_raw, str) else (sec_raw or [])
            except (json.JSONDecodeError, TypeError):
                sec_list = []
            ammo_map = ammo_map or {}
            for aid in sec_list:
                aname = ammo_map.get(aid.upper(), self.resolve_name('ammo', aid) or aid)
                items.append(self.make_item("弹药", aname, o)); o += 1
                p = None
                if conn is not None:
                    p = conn.execute("SELECT species, ammo_type FROM projectile_basic_info WHERE version_code=? AND projectile_id=?", (vc, aid)).fetchone()
                if p:
                    sp = (p['species'] or "").lower()
                    at = (p['ammo_type'] or "").upper()
                    detail_items: list[dict] = []
                    di = 0
                    be = None
                    if conn is not None:
                        be = conn.execute("SELECT alpha_damage, bullet_krupp, alpha_piercing_he, alpha_piercing_cs, bullet_speed, explosion_radius, burn_prob, bullet_mass, bullet_diameter, bullet_air_drag, bullet_always_ricochet_at, bullet_ricochet_at, bullet_detonator, bullet_detonator_threshold, bullet_cap_normalize_max FROM projectile_bullet_ext WHERE version_code=? AND projectile_id=?", (vc, aid)).fetchone()
                    if be:
                        if be['alpha_damage']: detail_items.append(self.make_item("标伤", f"{be['alpha_damage']:.0f}", di)); di += 1
                        detail_items.append(self.make_item("弹种", at, di)); di += 1
                        di = self._append_ammo_pen(detail_items, be, at, di)
                        if be['bullet_speed']: detail_items.append(self.make_item("弹速", f"{be['bullet_speed']:.0f}", di, unit="m/s")); di += 1
                        if be['burn_prob'] is not None and at == "HE": detail_items.append(self.make_item("起火概率", f"{be['burn_prob']*100:.2f}", di, unit="%")); di += 1
                        di = self._append_ammo_extra(detail_items, be, at, di, max_range_km=disp_range or None)
                    raw_ammo_types.append({"ammo_id": aid, "name": aname, "species": sp, "ammo_type": at, "detail_items": detail_items, "switchable": True})
        mods_raw = drum.get('switchablemode_modifiers_json')
        if mods_raw and mods_raw != '{}':
            try:
                mods = json.loads(mods_raw)
                if isinstance(mods, dict) and mods:
                    for mk, mv in sorted(mods.items()):
                        label = Mapping.MODIFIER_MAP.get(mk, mk)
                        ft = Mapping.format_modifier(mk, mv)
                        clr = Mapping.get_modifier_color(mk, mv)
                        items.append(self.make_item(label, ft, o, color=clr)); o += 1
            except (json.JSONDecodeError, TypeError):
                pass
        return items, o

    def _build_atba(self, conn, vc, ship_id, letter, result):
        """副炮数据（按 _build_hull 风格）"""
        ammo_map = self.get_name_map("ammo")
        rows = conn.execute(
            "SELECT * FROM ship_module_atba WHERE version_code=? AND ship_id=? AND config_group LIKE ? ORDER BY module_key",
            (vc, ship_id, f"{letter}%")).fetchall()
        if not rows:
            return
        items = []
        raw_ammo_types: list[dict] = []
        o = 0
        # WG：副炮模块级配置（控制组 AUTO/SWITCHABLE + 手动模式修饰符）
        acfg = conn.execute(
            "SELECT control_groups_json, manual_mode_modifiers_json FROM ship_module_atba_config "
            "WHERE version_code=? AND ship_id=? AND config_group=?",
            (vc, ship_id, letter)).fetchone()
        if acfg:
            try:
                cg = json.loads(acfg['control_groups_json'] or '{}') if acfg['control_groups_json'] else {}
            except (json.JSONDecodeError, TypeError):
                cg = {}
            try:
                mm = json.loads(acfg['manual_mode_modifiers_json'] or '{}') if acfg['manual_mode_modifiers_json'] else {}
            except (json.JSONDecodeError, TypeError):
                mm = {}
            auto_list = (cg.get('AUTO') or []) if isinstance(cg, dict) else []
            sw_list = (cg.get('SWITCHABLE') or []) if isinstance(cg, dict) else []
            if auto_list or sw_list:
                items.append(self.make_item("副炮控制组", "", o, row_type="sub_header")); o += 1
                if auto_list:
                    names = [self.resolve_name('gun', n) or n for n in auto_list]
                    items.append(self.make_item("自动模式", " / ".join(names), o)); o += 1
                if sw_list:
                    names = [self.resolve_name('gun', n) or n for n in sw_list]
                    items.append(self.make_item("可切换模式的副炮组", "\n".join(names), o)); o += 1
            if isinstance(mm, dict) and mm:
                items.append(self.make_item("副炮手动模式", "", o, row_type="sub_header")); o += 1
                for mk, mv in sorted(mm.items()):
                    label = Mapping.MODIFIER_MAP.get(mk, mk)
                    ft = Mapping.format_modifier(mk, mv)
                    clr = Mapping.get_modifier_color(mk, mv)
                    items.append(self.make_item(label, ft, o, color=clr)); o += 1
        for gi, g_row in enumerate(rows):
            if gi > 0:
                items.append({"row_type": "separator", "name": "", "value": "", "order": o}); o += 1
            g = dict(g_row)
            gname = self.resolve_name('gun', g.get('launcher_name') or g['module_key']) or g['module_key']
            items.append(self.make_item("炮塔", f"{gname} {g['count']:.0f}×{g['num_barrels']:.0f}", o)); o += 1
            if g['reload_time']: items.append(self.make_item("装填时间", str(g['reload_time']), o, unit="s")); o += 1
            if g['max_range']: items.append(self.make_item("最大射程", f"{g['max_range']:.2f}", o, unit="km")); o += 1
            if g['sigma']: items.append(self.make_item("弹着群系数(Sigma)", str(g['sigma']), o)); o += 1
            ir, mr, id_dist = g['ideal_radius'], g['min_radius'], g['ideal_distance']
            if ir and mr and id_dist:
                slope = (ir - mr) / (id_dist / 1000) if id_dist else 0
                intercept = mr * 30
                items.append(self.make_item("横向散步公式", f"{slope:.2f}R + {intercept:.0f}", o)); o += 1
            ammo_ids = self._sort_ammo_ids(conn, vc, [
                r["ammo_id"] for r in conn.execute(
                    "SELECT DISTINCT ammo_id FROM ship_weapon_projectiles WHERE version_code=? AND ship_id=? AND module_id=? AND slot_type='atba'",
                    (vc, ship_id, g['module_key'])).fetchall()
            ])
            for aid in ammo_ids:
                aname = ammo_map.get(aid.upper(), self.resolve_name('ammo', aid) or aid)
                items.append(self.make_item("弹药", aname, o)); o += 1
                p = conn.execute("SELECT species, ammo_type FROM projectile_basic_info WHERE version_code=? AND projectile_id=?", (vc, aid)).fetchone()
                if p:
                    sp = (p['species'] or "").lower()
                    at = (p['ammo_type'] or "").upper()
                    detail_items: list[dict] = []
                    di = 0
                    be = conn.execute("SELECT alpha_damage, bullet_krupp, alpha_piercing_he, alpha_piercing_cs, bullet_speed, explosion_radius, burn_prob, bullet_mass, bullet_diameter, bullet_air_drag, bullet_always_ricochet_at, bullet_ricochet_at, bullet_detonator, bullet_detonator_threshold, bullet_cap_normalize_max FROM projectile_bullet_ext WHERE version_code=? AND projectile_id=?", (vc, aid)).fetchone()
                    if be:
                        if be['alpha_damage']: detail_items.append(self.make_item("标伤", f"{be['alpha_damage']:.0f}", di)); di += 1
                        detail_items.append(self.make_item("弹种", at, di)); di += 1
                        di = self._append_ammo_pen(detail_items, be, at, di)
                        if be['bullet_speed']: detail_items.append(self.make_item("弹速", f"{be['bullet_speed']:.0f}", di, unit="m/s")); di += 1
                        if be['burn_prob'] is not None and at == "HE": detail_items.append(self.make_item("起火概率", f"{be['burn_prob']*100:.2f}", di, unit="%")); di += 1
                        di = self._append_ammo_extra(detail_items, be, at, di, max_range_km=g['max_range'] or None)
                    raw_ammo_types.append({"ammo_id": aid, "name": aname, "species": sp, "ammo_type": at, "detail_items": detail_items})
        if items:
            result[letter] = (items, raw_ammo_types)

    def _build_secondary_artillery(self, conn, vc, ship_id, letter, result):
        """次级主炮数据（按 _build_hull 风格）"""
        ammo_map = self.get_name_map("ammo")
        rows = conn.execute(
            "SELECT * FROM ship_module_secondary_artillery WHERE version_code=? AND ship_id=? AND config_group LIKE ? ORDER BY module_key",
            (vc, ship_id, f"{letter}%")).fetchall()
        if not rows:
            return
        items = []
        raw_ammo_types: list[dict] = []
        o = 0
        for g_row in rows:
            g = dict(g_row)
            gname = self.resolve_name('gun', g.get('launcher_name') or g['module_key']) or g['module_key']
            items.append(self.make_item("炮塔", f"{gname} {g['count']:.0f}×{g['num_barrels']:.0f}", o)); o += 1
            if g['reload_time']: items.append(self.make_item("装填时间", str(g['reload_time']), o, unit="s")); o += 1
            if g['max_range']: items.append(self.make_item("最大射程", f"{g['max_range']:.2f}", o, unit="km")); o += 1
            ir, mr, id_dist = g['ideal_radius'], g['min_radius'], g['ideal_distance']
            if ir and mr and id_dist:
                slope = (ir - mr) / (id_dist / 1000) if id_dist else 0
                intercept = mr * 30
                items.append(self.make_item("横向散步公式", f"{slope:.2f}R + {intercept:.0f}", o)); o += 1
            if g['sigma']: items.append(self.make_item("弹着群系数(Sigma)", str(g['sigma']), o)); o += 1
            if g.get('rotation_speed_h'):
                items.append(self.make_item("水平回转速度", f"{g['rotation_speed_h']:.1f}", o, unit="°/s")); o += 1
                rot_180 = 180.0 / g['rotation_speed_h']
                items.append(self.make_item("180°回转时间", f"{rot_180:.1f}", o, unit="s")); o += 1
            if g.get('rotation_speed_v'): items.append(self.make_item("垂直回转速度", f"{g['rotation_speed_v']:.1f}", o, unit="°/s")); o += 1
            if g.get('caliber'): items.append(self.make_item("口径", f"{g['caliber']*1000:.0f}", o, unit="mm")); o += 1
            ammo_ids = self._sort_ammo_ids(conn, vc, [
                r["ammo_id"] for r in conn.execute(
                    "SELECT DISTINCT ammo_id FROM ship_weapon_projectiles WHERE version_code=? AND ship_id=? AND module_id=? AND slot_type='secondary_artillery'",
                    (vc, ship_id, g['module_key'])).fetchall()
            ])
            for aid in ammo_ids:
                aname = ammo_map.get(aid.upper(), self.resolve_name('ammo', aid) or aid)
                items.append(self.make_item("弹药", aname, o)); o += 1
                p = conn.execute("SELECT species, ammo_type FROM projectile_basic_info WHERE version_code=? AND projectile_id=?", (vc, aid)).fetchone()
                if p:
                    sp = (p['species'] or "").lower()
                    at = (p['ammo_type'] or "").upper()
                    detail_items: list[dict] = []
                    di = 0
                    be = conn.execute("SELECT alpha_damage, bullet_krupp, alpha_piercing_he, alpha_piercing_cs, bullet_speed, explosion_radius, burn_prob, bullet_mass, bullet_diameter, bullet_air_drag, bullet_always_ricochet_at, bullet_ricochet_at, bullet_detonator, bullet_detonator_threshold, bullet_cap_normalize_max FROM projectile_bullet_ext WHERE version_code=? AND projectile_id=?", (vc, aid)).fetchone()
                    if be:
                        if be['alpha_damage']: detail_items.append(self.make_item("标伤", f"{be['alpha_damage']:.0f}", di)); di += 1
                        detail_items.append(self.make_item("弹种", at, di)); di += 1
                        di = self._append_ammo_pen(detail_items, be, at, di)
                        if be['bullet_speed']: detail_items.append(self.make_item("弹速", f"{be['bullet_speed']:.0f}", di, unit="m/s")); di += 1
                        if be['burn_prob'] is not None and at == "HE": detail_items.append(self.make_item("起火概率", f"{be['burn_prob']*100:.2f}", di, unit="%")); di += 1
                        di = self._append_ammo_extra(detail_items, be, at, di, max_range_km=g['max_range'] or None)
                    raw_ammo_types.append({"ammo_id": aid, "name": aname, "species": sp, "ammo_type": at, "detail_items": detail_items})
        if items:
            result[letter] = (items, raw_ammo_types)

    def _build_torpedoes(self, conn, vc, ship_id, letter, result, torpedo_key: str = ""):
        import json
        items = []
        raw_ammo_types: list[dict] = []
        o = 0
        ammo_map = self.get_name_map("ammo")
        # 配置栏传入的 torpedo_key 是顶层模块 key（如 A1_Torpedoes），
        # 通过 top_module_key 列过滤以显示对应的鱼雷变体
        if torpedo_key:
            rows = conn.execute(
                "SELECT * FROM ship_module_torpedoes WHERE version_code=? AND ship_id=? AND config_group LIKE ? AND top_module_key=? ORDER BY module_key",
                (vc, ship_id, f"{letter}%", torpedo_key)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM ship_module_torpedoes WHERE version_code=? AND ship_id=? AND config_group LIKE ? ORDER BY module_key",
                (vc, ship_id, f"{letter}%")).fetchall()
        if not rows:
            return
        # 查询模块级配置（useGroups / groups / useOneShot 等）
        tcfg = conn.execute(
            "SELECT * FROM ship_module_torpedo_config WHERE version_code=? AND ship_id=? AND config_group=?",
            (vc, ship_id, letter)).fetchone()
        # 按 (reload_time, ammo) 分组，同组鱼雷管合并显示（不同名称用 + 连接）
        group_map: dict[tuple, dict] = {}
        for t in rows:
            ammo_ids = self._sort_ammo_ids(conn, vc, [
                r["ammo_id"] for r in conn.execute(
                    "SELECT DISTINCT ammo_id FROM ship_weapon_projectiles "
                    "WHERE version_code=? AND ship_id=? AND module_id=? AND slot_type='torpedo'",
                    (vc, ship_id, t['module_key'])).fetchall()
            ])
            # 注意：key 包含 module_key，确保 A1/A2 等不同变体不合并
            key = (t['module_key'], t['reload_time'], tuple(ammo_ids))
            if key not in group_map:
                group_map[key] = {"module_key": t['module_key'],
                                  "reload_time": t['reload_time'], "ammo_ids": ammo_ids,
                                  "rotation_speed": t['rotation_speed'],
                                  "launchers": [], "total_count": 0,
                                  "torpedo_angles_narrow": t['torpedo_angles_narrow'],
                                  "torpedo_angles_wide": t['torpedo_angles_wide'],
                                  "use_one_shot": t['use_one_shot']}
            group_map[key]["launchers"].append(t['module_key'])
            group_map[key]["total_count"] += t['count']
        # 渲染
        for grp_key, grp in group_map.items():
            total_count = grp["total_count"]
            ammo_ids = grp["ammo_ids"]
            # 合并发射器名称
            launcher_names = []
            seen_names = set()
            launcher_counts = []
            launcher_barrels = []
            mk_lookup = {t['module_key']: t for t in rows}
            for mk in grp["launchers"]:
                t = mk_lookup.get(mk)
                if t is None:
                    continue
                try:
                    ln = t['launcher_name'] or mk
                except (KeyError, IndexError):
                    ln = mk
                dname = self.resolve_name('gun', ln) or ln
                cnt = t['count'] or 0
                br = t['num_barrels'] or 1
                if dname not in seen_names:
                    seen_names.add(dname)
                    launcher_names.append(dname)
                    launcher_counts.append(cnt)
                    launcher_barrels.append(br)
                else:
                    idx = launcher_names.index(dname)
                    launcher_counts[idx] += cnt
                    if launcher_barrels[idx] != br:
                        launcher_barrels[idx] = br  # take last barrel count
            if len(launcher_names) == 1:
                name_str = f"{launcher_names[0]} {launcher_counts[0]}×{launcher_barrels[0]}"
            else:
                parts = [f"{n} {c}×{b}" for n, c, b in zip(launcher_names, launcher_counts, launcher_barrels)]
                name_str = " + ".join(parts)
            # 有 useGroups 时按分组显示，不显示合并行
            use_groups = tcfg and tcfg['use_groups']
            if not use_groups:
                items.append(self.make_item("鱼雷发射管", name_str, o)); o += 1

            # 模块级鱼雷分组信息（useGroups）
            if use_groups:
                import json
                try:
                    groups_names = json.loads(tcfg['groups_names_json']) if tcfg['groups_names_json'] else []
                    groups_counts = json.loads(tcfg['groups_counts_json']) if tcfg['groups_counts_json'] else []
                    # 构建 group_id → name 映射（从 po_translations 查询中文名）
                    group_name_map: dict[int, str] = {}
                    for gn_entry in groups_names:
                        gname_key = gn_entry[0]
                        gids = gn_entry[1]
                        resolved_name = gname_key
                        try:
                            nm_row = conn.execute(
                                "SELECT lang_zh FROM name_mappings WHERE category=? AND key_name=? LIMIT 1",
                                ("torpedo_group", gname_key)).fetchone()
                            if nm_row and nm_row['lang_zh']:
                                resolved_name = nm_row['lang_zh']
                        except Exception:
                            pass
                        for gid in gids:
                            group_name_map[gid] = resolved_name
                    # 解析 loaders_json → group_id → loader_count
                    group_loaders: dict[int, int] = {}
                    try:
                        loaders_data = json.loads(tcfg['loaders_json']) if tcfg['loaders_json'] else []
                        for loader_entry in loaders_data:
                            lc = loader_entry[0]
                            gids = loader_entry[1]
                            for gid in gids:
                                group_loaders[gid] = lc
                    except Exception:
                        pass
                    # 按 group_id 排序显示，每行带上装填手/单次装填量
                    for gc in groups_counts:
                        gid = gc['group_id']
                        gname = group_name_map.get(gid, f"分组{gid}")
                        launchers = gc.get('launchers', [])
                        if len(launchers) == 1:
                            ln = launchers[0]
                            dname = self.resolve_name('gun', ln['name']) or ln['name']
                            cnt_str = f"{dname} {ln['count']}×{ln['num_barrels']}"
                        else:
                            parts = []
                            for ld in launchers:
                                dname = self.resolve_name('gun', ld['name']) or ld['name']
                                parts.append(f"{dname} {ld['count']}×{ld['num_barrels']}")
                            cnt_str = " + ".join(parts)
                        items.append(self.make_item(gname, cnt_str, o)); o += 1
                    # 按分组顺序显示装填手数量
                    if group_loaders:
                        parts = []
                        for gc in groups_counts:
                            lc = group_loaders.get(gc['group_id'], 0)
                            if lc:
                                parts.append(str(lc))
                        if parts:
                            items.append(self.make_item("鱼雷管装填手数量", " / ".join(parts), o)); o += 1
                except Exception:
                    items.append(self.make_item("鱼雷发射管", name_str, o)); o += 1

            # 先检测是否有弹鼓/充能数据
            has_drum = False
            for mk in grp["launchers"]:
                ext = conn.execute(
                    "SELECT * FROM ship_module_torpedo_ext WHERE version_code=? AND ship_id=? AND config_group LIKE ? AND module_key=?",
                    (vc, ship_id, f"{letter}%", mk)).fetchone()
                if ext and ext['is_drum_chargeable']:
                    has_drum = True
                    break
            # 有弹鼓机制时不显示基础装填时间，用弹鼓数据替代
            if has_drum:
                items.append(self.make_item("特殊机制", "弹鼓式装填", o, row_type="header")); o += 1
                ct = ext['drum_charge_time']
                mc = ext['drum_max_charges']
                if ct: items.append(self.make_item("单发装填时间", f"{ct:.0f}", o, unit="s")); o += 1
                if mc: items.append(self.make_item("最大预装填数量", f"{mc:.0f} 枚", o)); o += 1
                frt = ext['drum_full_reload_time']
                if frt and frt != ct * mc:
                    items.append(self.make_item("完全装填时间", f"{frt:.0f}", o, unit="s")); o += 1
            else:
                rt_val = grp.get('reload_time', 0)
                if rt_val:
                    items.append(self.make_item("装填时间", str(rt_val), o, unit="s")); o += 1
                    # 有 2+ 弹药时额外显示弹药切换时间（ammoSwitchCoeff × shotDelay）
                    if tcfg and tcfg['ammo_switch_coeff'] and len(ammo_ids) >= 2:
                        switch_time = tcfg['ammo_switch_coeff'] * rt_val
                        items.append(self.make_item("弹药切换时间", f"{switch_time:.1f}", o, unit="s")); o += 1
            if tcfg and tcfg['module_reload_time']:
                items.append(self.make_item("鱼雷切换时间", str(tcfg['module_reload_time']), o, unit="s")); o += 1
            if grp.get('rotation_speed'):
                items.append(self.make_item("水平回转速度", f"{grp['rotation_speed']:.1f}", o, unit="°/s")); o += 1
                rot_180 = 180.0 / grp['rotation_speed']
                items.append(self.make_item("180°回转时间", f"{rot_180:.1f}", o, unit="s")); o += 1
            # 鱼雷散布角度（窄/宽）
            narrow_angle = grp.get('torpedo_angles_narrow', 0)
            wide_angle = grp.get('torpedo_angles_wide', 0)
            if narrow_angle > 0 or wide_angle > 0:
                angle_str = f"{narrow_angle}°"
                if wide_angle != narrow_angle:
                    angle_str += f" / {wide_angle}°"
                items.append(self.make_item("散布角度", angle_str, o, unit="")); o += 1
            # 单发射击
            if grp.get('use_one_shot') or (tcfg and tcfg['use_one_shot']):
                items.append(self.make_item("单发射击", "支持", o, color="#1b8a1b")); o += 1
                if tcfg and tcfg['one_shot_wait_time']:
                    items.append(self.make_item("单发间隔", str(tcfg['one_shot_wait_time']), o, unit="s")); o += 1
            for aid in ammo_ids:
                aname = ammo_map.get(aid.upper(), aid)
                p = conn.execute(
                    "SELECT pb.species, pb.ammo_type, pb.custom_ui_postfix, te.alpha_damage, te.damage, te.torpedo_speed, "
                    "te.torpedo_max_dist, te.torpedo_visibility, te.torpedo_arming_time, "
                    "te.burn_prob, te.uw_critical, te.is_deep_water, te.flood_generation, "
                    "te.deep_water_ignore_classes, te.affected_by_ptz, te.distance_of_damage_json "
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
                    items.append(self.make_item("弹药", aname, o)); o += 1
                    detail_items: list[dict] = []
                    di = 0
                    ad = p['alpha_damage'] or 0
                    if ad: detail_items.append(self.make_item("标伤", f"{ad * 0.33:.0f}", di)); di += 1
                    detail_items.append(self.make_item("弹种", dtype, di)); di += 1
                    if is_deep and p['deep_water_ignore_classes']:
                        _ignored = [x.strip() for x in p['deep_water_ignore_classes'].split(",") if x.strip() and x.strip() != "Auxiliary"]
                        _ignored_cn = "、".join(Mapping.SHIP_CLASS_MAP.get(x, x) for x in _ignored)
                        _all_types = ["Destroyer", "Cruiser", "Battleship", "AirCarrier", "Submarine"]
                        _hittable_cn = "、".join(Mapping.SHIP_CLASS_MAP.get(x, x) for x in _all_types if x not in _ignored)
                        detail_items.append(self.make_item("可攻击目标", _hittable_cn, di, color="#1b8a1b")); di += 1
                        detail_items.append(self.make_item("无法攻击目标", _ignored_cn, di, color="#d32f2f")); di += 1
                    if p['torpedo_speed']: detail_items.append(self.make_item("航速", f"{p['torpedo_speed']:.0f}", di, unit="kts")); di += 1
                    dist = p['torpedo_max_dist']
                    if dist: detail_items.append(self.make_item("射程", f"{dist * 0.03:.2f}", di, unit="km")); di += 1
                    if p['torpedo_visibility']: detail_items.append(self.make_item("被发现距离", f"{p['torpedo_visibility']:.2f}", di, unit="km")); di += 1
                    if p['torpedo_arming_time']: detail_items.append(self.make_item("鱼雷上浮时间", f"{p['torpedo_arming_time']:.2f}", di, unit="s")); di += 1
                    # 鱼雷上浮距离 = 上浮时间 × 航速（1kts = 0.514444m/s）
                    if p['torpedo_arming_time'] and p['torpedo_speed']:
                        arm_dist = p['torpedo_speed'] * 0.514444 * p['torpedo_arming_time']
                        detail_items.append(self.make_item("鱼雷上浮距离", f"{arm_dist:.0f}", di, unit="m")); di += 1
                    if p['flood_generation'] and p['uw_critical']:
                        detail_items.append(self.make_item("漏水系数", f"{p['uw_critical']:.2f}", di, details=[{"name":"进水基础概率", "value": str(p['flood_generation'])}])); di += 1
                    if is_burn and p['burn_prob']:
                        detail_items.append(self.make_item("基础点火率", f"{p['burn_prob']*100:.0f}", di, unit="%")); di += 1
                    if sge:
                        if sge['search_radius']: detail_items.append(self.make_item("搜索半径", f"{sge['search_radius']:.2f}", di, unit="km")); di += 1
                        if sge['search_angle']: detail_items.append(self.make_item("搜索角度", f"{sge['search_angle']:.0f}", di, unit="°")); di += 1
                        if sge['max_yaw']: detail_items.append(self.make_item("最大转向角", f"{sge['max_yaw']:.0f}", di, unit="°")); di += 1
                        if sge['max_vertical_speed']: detail_items.append(self.make_item("最大垂直速度", f"{sge['max_vertical_speed']:.2f}", di, unit="kts")); di += 1
                        if sge['max_depth_level']: detail_items.append(self.make_item("最大深度级别", f"{sge['max_depth_level']:.0f}", di)); di += 1
                        if sge['target_lost_degradation_time']: detail_items.append(self.make_item("丢失目标降级时间", f"{sge['target_lost_degradation_time']:.1f}", di, unit="s")); di += 1
                    _dod = p['distance_of_damage_json']
                    _dmg_trend = None
                    if _dod:
                        try:
                            _arr = json.loads(_dod)
                            _parts = []
                            if isinstance(_arr, (list, tuple)) and len(_arr) >= 1:
                                _first = _arr[0]
                                if isinstance(_first, (list, tuple)) and len(_first) >= 2:
                                    _parts.append(f"前 {_first[0]*0.03:.2f}km 保持 {_first[1]*100:g}% 伤害")
                                if len(_arr) >= 2:
                                    for _pair in _arr[1:-1]:
                                        if isinstance(_pair, (list, tuple)) and len(_pair) >= 2:
                                            _parts.append(f"到 {_pair[0]*0.03:.2f}km 渐变为 {_pair[1]*100:g}% 伤害")
                                    _last = _arr[-1]
                                    if isinstance(_last, (list, tuple)) and len(_last) >= 2:
                                        _parts.append(f"直到 {_last[0]*0.03:.2f}km 渐变并保持 {_last[1]*100:g}% 伤害")
                            if _parts:
                                detail_items.append(self.make_item("动态鱼雷伤害", '\n'.join(_parts), di)); di += 1
                            if len(_arr) >= 2 and isinstance(_arr[0], (list, tuple)) and isinstance(_arr[1], (list, tuple)) \
                                    and len(_arr[0]) >= 2 and len(_arr[1]) >= 2:
                                _a, _b = _arr[0][1], _arr[1][1]
                                if _a is not None and _b is not None:
                                    _dmg_trend = "increase" if _a < _b else ("decrease" if _a > _b else None)
                        except (json.JSONDecodeError, TypeError, ValueError):
                            pass
                    raw_ammo_types.append({
                        "ammo_id": aid, "name": aname,
                        "species": p['species'] or "", "ammo_type": dtype,
                        "raw_ammo_type": p['ammo_type'] or "",
                        "torpedo_postfix": postfix,
                        "is_guided": is_guided,
                        "dmg_dist_trend": _dmg_trend,
                        "detail_items": detail_items,
                    })
                else:
                    items.append(self.make_item(aname, "", o)); o += 1
        if items:
            result[letter] = (items, raw_ammo_types)

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
                    items.append(self.make_item(f"{labels[key]}伤害", f"{dps_val:.0f}", o)); o += 1
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
        raw_ammo_types: list[dict] = []
        o = 0
        # 按 stats 分组，同组深弹合并
        group_map: dict[tuple, dict] = {}
        for d in conn.execute(
            "SELECT * FROM ship_module_depth_charge WHERE version_code=? AND ship_id=? AND config_group LIKE ?",
            (vc, ship_id, f"{letter}%")).fetchall():
            key = (d['reload_time'], d['shot_delay'], d['max_packs'], d['num_shots'],
                   d['damage'], d['dc_speed'], d['dc_timer'], d['dc_max_depth'],
                   d['depth_splash_size'], d['num_bombs'], d['projectile_id'])
            if key not in group_map:
                group_map[key] = {
                    "reload_time": d['reload_time'],
                    "gun_names": [], "total_count": 0,
                    "row": dict(d),
                }
            group_map[key]["gun_names"].append((d['gun_name'], d['count']))
            group_map[key]["total_count"] += d['count']
        for grp in group_map.values():
            # 合并名称
            seen = {}
            for gn, cnt in grp["gun_names"]:
                dname = self.resolve_name('gun', gn) or gn
                seen[dname] = seen.get(dname, 0) + cnt
            if len(seen) == 1:
                name_str = f"{list(seen.keys())[0]} {list(seen.values())[0]}×1"
            else:
                parts = [f"{n} {c}×1" for n, c in seen.items()]
                name_str = " + ".join(parts)
            items.append(self.make_item("深弹发射器", name_str, o)); o += 1
            rd = grp["row"]
            if rd['reload_time']: items.append(self.make_item("装填时间", str(rd['reload_time']), o, unit="s")); o += 1
            items.append(self.make_item("弹药", "深弹", o)); o += 1
            detail_items: list[dict] = []
            di = 0
            if rd['shot_delay']: detail_items.append(self.make_item("发射间隔", str(rd['shot_delay']), di, unit="s")); di += 1
            if rd['max_packs']: detail_items.append(self.make_item("最大组数", str(rd['max_packs']), di)); di += 1
            if rd['num_shots']: detail_items.append(self.make_item("每组数量", str(rd['num_shots']), di)); di += 1
            if rd['damage']: detail_items.append(self.make_item("标伤", f"{rd['damage']:.0f}", di)); di += 1
            if rd['dc_speed']: detail_items.append(self.make_item("下沉速度", f"{rd['dc_speed']:.2f}", di, unit="m/s")); di += 1
            if rd['dc_timer']: detail_items.append(self.make_item("引信定时", f"{rd['dc_timer']:.2f}", di, unit="s")); di += 1
            if rd['dc_max_depth']: detail_items.append(self.make_item("最大深度", f"{abs(rd['dc_max_depth']):.0f}", di, unit="m")); di += 1
            if rd['depth_splash_size']: detail_items.append(self.make_item("溅射范围", f"{rd['depth_splash_size']:.2f}", di, unit="m")); di += 1
            raw_ammo_types.append({
                "ammo_id": rd['projectile_id'],
                "name": self.resolve_name('ammo', rd['projectile_id']) or rd['projectile_id'],
                "species": "DepthCharge",
                "ammo_type": "深弹",
                "detail_items": detail_items,
            })
        if items:
            result[letter] = (items, raw_ammo_types)

    def _build_pinger(self, conn, vc, ship_id, letter, result, sonar_key=""):
        items = []
        o = 0
        if sonar_key:
            rows = conn.execute(
                "SELECT * FROM ship_module_pinger WHERE version_code=? AND ship_id=? AND config_group LIKE ? AND module_key=? ORDER BY module_key",
                (vc, ship_id, f"{letter}%", sonar_key)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM ship_module_pinger WHERE version_code=? AND ship_id=? AND config_group LIKE ? ORDER BY module_key",
                (vc, ship_id, f"{letter}%")).fetchall()
        if not rows:
            return
        for idx, p in enumerate(rows):
            mod_key = f"声呐模块 {idx + 1}"
            if p['wave_reload_time']: items.append(self.make_item("声呐装填时间", str(p['wave_reload_time']), o, unit="s")); o += 1
            if p['wave_distance']: items.append(self.make_item("声呐射程", f"{p['wave_distance'] / 1000:.2f}", o, unit="km")); o += 1
            if p['sector_lifetime']: items.append(self.make_item("脉冲持续时间", str(p['sector_lifetime']), o, unit="s")); o += 1
            if p['wave_speed']: items.append(self.make_item("脉冲速度", str(p['wave_speed']), o, unit="m/s")); o += 1
            if p['exposing_waves']: items.append(self.make_item("发射后脉冲显示次数", str(p['exposing_waves']), o)); o += 1
        if items:
            result[letter] = (items, [])

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
            "MineBomber": "水雷轰炸机",
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
        for ptype in ("Fighter", "DiveBomber", "TorpedoBomber", "SkipBomber", "MineBomber", "其他"):
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
                config_labels.append(key)  # 内部 key 作为唯一标识
                config_label_map[key] = disp_name  # 内部 key → 显示名
                items: list[dict] = []
                raw_ammo_types: list[dict] = []
                raw_consumables: list[dict] = []
                o = 0
                group = prefix_map[key]
                is_tactical = False
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
                        # 战术机组：机库初始值为 0（无预备队，整队恢复）
                        if pid.get('hangar_start_value', 1) == 0:
                            is_tactical = True
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
                        if pid.get('hp'): items.append(self.make_item("单架飞机血量", f"{pid['hp']:.0f}", o)); o += 1
                        _mfa = pid.get('max_forsage_amount')
                        if _mfa:
                            items.append(self.make_item("引擎加速时间", f"{_mfa:.0f}", o, unit="s")); o += 1
                            _frg = pid.get('forsage_regeneration')
                            if _frg:
                                items.append(self.make_item("引擎加速冷却时间", f"{_mfa / _frg:.0f}", o, unit="s")); o += 1
                        _jato_dur = pid.get('jato_duration')
                        if _jato_dur:
                            items.append(self.make_item("喷气式助推器作用时间", f"{_jato_dur:.0f}", o, unit="s")); o += 1
                            _jato_mult = pid.get('jato_speed_mult')
                            _cspeed = smwb or pid.get('cruising_speed')
                            if _cspeed and _jato_mult:
                                items.append(self.make_item("喷气式助推器生效期间巡航速度", f"{_cspeed * _jato_mult:.0f}", o, unit="kts")); o += 1
                        ac = pid.get('attack_count') or 0
                        if ac and ptype != "MineBomber": items.append(self.make_item("载弹量", str(ac), o)); o += 1
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
                    minefield_override_proj = None; _mf = None
                    # ── 水雷机：先从雷场数据中读取属性，再取 seaMine 作弹药 ──
                    if pid.get("field_minefield"):
                        _mf = conn.execute(
                            "SELECT radius, activation_delay, life_time, mines, distribution_json, sea_mine_id, depth "
                            "FROM minefield_info WHERE version_code=? AND minefield_id=?",
                            (vc, pid["field_minefield"])).fetchone()
                        if _mf and _mf["sea_mine_id"]:
                            minefield_override_proj = _mf["sea_mine_id"]
                    # ── 弹药数据（收集到 raw_ammo_types）──
                    arm = p.get('armament_name') or ""
                    proj_id = minefield_override_proj or arm or bname
                    if proj_id:
                        pbi = conn.execute(
                            "SELECT species, ammo_type, custom_ui_postfix FROM projectile_basic_info WHERE version_code=? AND projectile_id=?",
                            (vc, proj_id)).fetchone()
                        if pbi:
                            species = pbi['species'] or ""
                            atype = pbi['ammo_type'] or ""
                            ammo_name = ammo_map.get(proj_id.upper(), self.resolve_name('ammo', proj_id) or proj_id)
                            detail_items: list[dict] = []
                            di = 0
                            _dmg_trend = None
                            _ac = "alpha_damage, bullet_krupp, alpha_piercing_he, alpha_piercing_cs, bullet_speed, explosion_radius, burn_prob, bullet_mass, bullet_diameter, bullet_air_drag, bullet_always_ricochet_at, bullet_ricochet_at, bullet_detonator, bullet_detonator_threshold, bullet_cap_normalize_max"
                            _bc = f"damage, skips_json, max_skip_angle, {_ac}"
                            if species in ("Bullet", "HE"):
                                be = conn.execute(f"SELECT {_ac} FROM projectile_bullet_ext WHERE version_code=? AND projectile_id=?", (vc, proj_id)).fetchone()
                                if be:
                                    if be['alpha_damage']: detail_items.append(self.make_item("标伤", f"{be['alpha_damage']:.0f}", di)); di += 1
                                    detail_items.append(self.make_item("弹种", atype, di)); di += 1
                                    di = self._append_ammo_pen(detail_items, be, atype, di)
                                    if be['bullet_speed']: detail_items.append(self.make_item("弹速", f"{be['bullet_speed']:.0f}", di, unit="m/s")); di += 1
                                    if be['burn_prob'] is not None and atype == "HE": detail_items.append(self.make_item("起火概率", f"{be['burn_prob']*100:.2f}", di, unit="%")); di += 1
                                    di = self._append_ammo_extra(detail_items, be, atype, di)
                            elif species == "Bomb":
                                be = conn.execute(f"SELECT {_bc} FROM projectile_bomb_ext WHERE version_code=? AND projectile_id=?", (vc, proj_id)).fetchone()
                                if be:
                                    if be['alpha_damage']: detail_items.append(self.make_item("标伤", f"{be['alpha_damage']:.0f}", di)); di += 1
                                    detail_items.append(self.make_item("弹种", atype, di)); di += 1
                                    di = self._append_ammo_pen(detail_items, be, atype, di)
                                    if be['bullet_speed']: detail_items.append(self.make_item("弹速", f"{be['bullet_speed']:.0f}", di, unit="m/s")); di += 1
                                    if be['burn_prob'] is not None and atype == "HE": detail_items.append(self.make_item("起火概率", f"{be['burn_prob']*100:.2f}", di, unit="%")); di += 1
                                    di = self._append_ammo_extra(detail_items, be, atype, di)
                                    di = self._append_skip_data(detail_items, be, di)
                            elif species == "SkipBomb":
                                be = conn.execute(f"SELECT {_bc} FROM projectile_bomb_ext WHERE version_code=? AND projectile_id=?", (vc, proj_id)).fetchone()
                                if be:
                                    if be['alpha_damage']: detail_items.append(self.make_item("标伤", f"{be['alpha_damage']:.0f}", di)); di += 1
                                    detail_items.append(self.make_item("弹种", atype, di)); di += 1
                                    di = self._append_ammo_pen(detail_items, be, atype, di)
                                    if be['bullet_speed']: detail_items.append(self.make_item("弹速", f"{be['bullet_speed']:.0f}", di, unit="m/s")); di += 1
                                    if be['burn_prob'] is not None and atype == "HE": detail_items.append(self.make_item("起火概率", f"{be['burn_prob']*100:.2f}", di, unit="%")); di += 1
                                    di = self._append_ammo_extra(detail_items, be, atype, di)
                                    di = self._append_skip_data(detail_items, be, di)
                            elif species == "Rocket":
                                re = conn.execute(f"SELECT damage, {_ac} FROM projectile_rocket_ext WHERE version_code=? AND projectile_id=?", (vc, proj_id)).fetchone()
                                if re:
                                    if re['alpha_damage']: detail_items.append(self.make_item("标伤", f"{re['alpha_damage']:.0f}", di)); di += 1
                                    detail_items.append(self.make_item("弹种", atype, di)); di += 1
                                    di = self._append_ammo_pen(detail_items, re, atype, di)
                                    if re['bullet_speed']: detail_items.append(self.make_item("弹速", f"{re['bullet_speed']:.0f}", di, unit="m/s")); di += 1
                                    if re['burn_prob'] is not None and atype == "HE": detail_items.append(self.make_item("起火概率", f"{re['burn_prob']*100:.2f}", di, unit="%")); di += 1
                                    di = self._append_ammo_extra(detail_items, re, atype, di)
                                asq = conn.execute("SELECT attack_sequence_durations FROM projectile_rocket_ext WHERE version_code=? AND projectile_id=?", (vc, proj_id)).fetchone()
                                if asq and asq['attack_sequence_durations']:
                                    di = self._append_strafe_time(detail_items, asq['attack_sequence_durations'], di)
                            elif species in ("PlaneSeaMine", "Mine"):
                                be = conn.execute(
                                    "SELECT alpha_damage, explosion_radius, burn_prob, "
                                    "flood_generation, uw_critical, health, max_depth, fall_time, "
                                    "affected_by_ptz, apply_ptz_coeff "
                                    "FROM projectile_mine_ext WHERE version_code=? AND projectile_id=?", (vc, proj_id)).fetchone()
                                if be:
                                    if be['alpha_damage']: detail_items.append(self.make_item("最大伤害", f"{be['alpha_damage']:.0f}", di)); di += 1
                                    if be['health']: detail_items.append(self.make_item("水雷生命值", f"{be['health']:.0f}", di)); di += 1
                                    if be['max_depth'] is not None: detail_items.append(self.make_item("最大深度", f"{abs(be['max_depth']):.0f}", di, unit="m")); di += 1
                                    if be['uw_critical']: detail_items.append(
                                        self.make_item("漏水系数", f"{be['uw_critical']:.2f}", di,
                                            details=[{"name":"进水基础概率","value":"是" if be['flood_generation'] else "否"}])
                                    ); di += 1
                                # ── 上级雷场属性 ──
                                if _mf:
                                    # 激活时间使用飞机本体炸弹的 fall_time（水雷入水时间）
                                    _fall_src = None
                                    if bname:
                                        _fall_src = conn.execute(
                                            "SELECT fall_time FROM projectile_mine_ext WHERE version_code=? AND projectile_id=?",
                                            (vc, bname)).fetchone()
                                    _ft = _fall_src['fall_time'] if _fall_src and _fall_src['fall_time'] else 0
                                    _ac = pid.get('attack_count') or 0
                                    _ai = pid.get('attack_interval') or 0
                                    _ad = _mf['activation_delay'] or 0
                                    _total = (_ac - 1) * _ai + _ft + _ad
                                    if _total: detail_items.append(self.make_item("激活时间", f"{_total:.1f}", di, unit="s")); di += 1
                                    if _mf["life_time"]: detail_items.append(self.make_item("雷区持续时间", f"{_mf['life_time']:.1f}", di, unit="s")); di += 1
                                    if _mf["radius"]: detail_items.append(self.make_item("雷区半径", f"{_mf['radius']:.0f}", di, unit="m")); di += 1
                                    _dist = json.loads(_mf["distribution_json"]) if _mf["distribution_json"] else {}
                                    if _dist:
                                        _keys = sorted([float(k) for k in _dist.keys()])
                                        if _keys:
                                            if _keys[0] > 0: detail_items.append(self.make_item("散布圈最小半径", f"{_keys[0]:.0f}", di, unit="m")); di += 1
                                            if _keys[-1] > 0: detail_items.append(self.make_item("散布圈最大半径", f"{_keys[-1]:.0f}", di, unit="m")); di += 1
                                    if _mf["depth"] is not None: detail_items.append(self.make_item("雷区深度", f"{_mf['depth']:.1f}", di, unit="m")); di += 1
                                    if _mf["mines"] is not None and _mf["mines"] > 0:
                                        detail_items.append(self.make_item("水雷数量", str(_mf["mines"]), di)); di += 1
                                detail_items.append(self.make_item("弹种", "水雷", di)); di += 1
                            elif species in ("Torpedo", "TorpedoBomber"):
                                te = conn.execute(
                                    "SELECT alpha_damage, damage, torpedo_speed, torpedo_max_dist, torpedo_visibility, "
                                    "torpedo_arming_time, burn_prob, uw_critical, flood_generation, is_deep_water, "
                                    "deep_water_ignore_classes, alert_dist, affected_by_ptz, distance_of_damage_json "
                                    "FROM projectile_torpedo_ext WHERE version_code=? AND projectile_id=?", (vc, proj_id)).fetchone()
                                if te:
                                    sge = conn.execute(
                                        "SELECT search_radius, search_angle, max_yaw, max_vertical_speed, max_depth_level, "
                                        "target_lost_degradation_time, "
                                        "drop_dist_aircarrier, drop_dist_battleship, drop_dist_cruiser, "
                                        "drop_dist_destroyer, drop_dist_submarine, drop_dist_default "
                                        "FROM projectile_torpedo_sub_guidance_ext WHERE version_code=? AND projectile_id=?", (vc, proj_id)).fetchone()
                                    is_guided = sge is not None; is_deep = te['is_deep_water']; is_burn = bool(te['burn_prob'])
                                    dtype = "声呐导向鱼雷" if is_guided else ("深水鱼雷" if is_deep else ("热能鱼雷" if is_burn else "鱼雷"))
                                    ad = te['alpha_damage'] or 0
                                    if ad: detail_items.append(self.make_item("标伤", f"{ad * 0.33:.0f}", di)); di += 1
                                    detail_items.append(self.make_item("弹种", atype, di)); di += 1
                                    detail_items.append(self.make_item("类型", dtype, di)); di += 1
                                    if is_deep and te['deep_water_ignore_classes']:
                                        _ignored = [x.strip() for x in te['deep_water_ignore_classes'].split(",") if x.strip() and x.strip() != "Auxiliary"]
                                        _ignored_cn = "、".join(Mapping.SHIP_CLASS_MAP.get(x, x) for x in _ignored)
                                        _all_types = ["Destroyer", "Cruiser", "Battleship", "AirCarrier", "Submarine"]
                                        _hittable_cn = "、".join(Mapping.SHIP_CLASS_MAP.get(x, x) for x in _all_types if x not in _ignored)
                                        detail_items.append(self.make_item("可攻击目标", _hittable_cn, di, color="#1b8a1b")); di += 1
                                        detail_items.append(self.make_item("无法攻击目标", _ignored_cn, di, color="#d32f2f")); di += 1
                                    if te['torpedo_speed']: detail_items.append(self.make_item("航速", f"{te['torpedo_speed']:.0f}", di, unit="kts")); di += 1
                                    if te['torpedo_max_dist'] is not None: detail_items.append(self.make_item("最大射程", f"{(te['torpedo_max_dist'] * 30) / 1000:.2f}", di, unit="km")); di += 1
                                    if te['flood_generation'] and te['uw_critical']:
                                        detail_items.append(self.make_item("漏水系数", f"{te['uw_critical']:.2f}", di,
                                            details=[{"name":"进水基础概率","value":str(te['flood_generation'])}])); di += 1
                                    if te['torpedo_visibility']: detail_items.append(self.make_item("鱼雷被侦测距离", f"{te['torpedo_visibility']:.2f}", di, unit="km")); di += 1
                                    if te['torpedo_arming_time']: detail_items.append(self.make_item("鱼雷上浮时间", f"{te['torpedo_arming_time']:.2f}", di, unit="s")); di += 1
                                    if is_burn and te['burn_prob']: detail_items.append(self.make_item("基础点火率", f"{te['burn_prob']*100:.0f}", di, unit="%")); di += 1
                                    if is_guided:
                                        if sge['search_radius']: detail_items.append(self.make_item("搜索半径", f"{sge['search_radius']:.2f}", di, unit="km")); di += 1
                                        if sge['search_angle']: detail_items.append(self.make_item("搜索角度", f"{sge['search_angle']:.0f}", di, unit="°")); di += 1
                                        if sge['max_yaw']: detail_items.append(self.make_item("最大转向角", f"{sge['max_yaw']:.0f}", di, unit="°")); di += 1
                                        if sge['max_vertical_speed']: detail_items.append(self.make_item("最大垂直速度", f"{sge['max_vertical_speed']:.2f}", di, unit="kts")); di += 1
                                        if sge['max_depth_level']: detail_items.append(self.make_item("最大深度级别", f"{sge['max_depth_level']:.0f}", di)); di += 1
                                        if sge['target_lost_degradation_time']: detail_items.append(self.make_item("丢失目标降级时间", f"{sge['target_lost_degradation_time']:.1f}", di, unit="s")); di += 1
                                        drop_parts = []
                                        for ship_cls, col in [("航母","drop_dist_aircarrier"),("战列舰","drop_dist_battleship"),("巡洋舰","drop_dist_cruiser"),("驱逐舰","drop_dist_destroyer"),("潜艇","drop_dist_submarine"),("默认","drop_dist_default")]:
                                            if sge[col] is not None: drop_parts.append(f"{ship_cls}: {sge[col]} m")
                                        if drop_parts: detail_items.append(self.make_item("放弃追踪距离", ' | '.join(drop_parts), di)); di += 1
                                    # distanceOfDamage 为鱼雷通用属性（不限声呐导向），置于 is_guided 块外
                                    _dod = te['distance_of_damage_json']
                                    _dmg_trend = None
                                    if _dod:
                                        try:
                                            _arr = json.loads(_dod)
                                            _parts = []
                                            if isinstance(_arr, (list, tuple)) and len(_arr) >= 1:
                                                _first = _arr[0]
                                                if isinstance(_first, (list, tuple)) and len(_first) >= 2:
                                                    _parts.append(f"前 {_first[0]*0.03:.2f}km 保持 {_first[1]*100:g}% 伤害")
                                                if len(_arr) >= 2:
                                                    for _pair in _arr[1:-1]:
                                                        if isinstance(_pair, (list, tuple)) and len(_pair) >= 2:
                                                            _parts.append(f"到 {_pair[0]*0.03:.2f}km 渐变为 {_pair[1]*100:g}% 伤害")
                                                    _last = _arr[-1]
                                                    if isinstance(_last, (list, tuple)) and len(_last) >= 2:
                                                        _parts.append(f"直到 {_last[0]*0.03:.2f}km 渐变并保持 {_last[1]*100:g}% 伤害")
                                            if _parts:
                                                detail_items.append(self.make_item("动态鱼雷伤害", '\n'.join(_parts), di)); di += 1
                                            if len(_arr) >= 2 and isinstance(_arr[0], (list, tuple)) and isinstance(_arr[1], (list, tuple)) \
                                                    and len(_arr[0]) >= 2 and len(_arr[1]) >= 2:
                                                _a, _b = _arr[0][1], _arr[1][1]
                                                if _a is not None and _b is not None:
                                                    _dmg_trend = "increase" if _a < _b else ("decrease" if _a > _b else None)
                                        except (json.JSONDecodeError, TypeError, ValueError):
                                            pass
                            raw_ammo_types.append({
                                "ammo_id": proj_id, "name": ammo_name,
                                "species": species, "ammo_type": atype,
                                "raw_ammo_type": pbi['ammo_type'] or "",
                                "torpedo_postfix": pbi['custom_ui_postfix'] or "",
                                "dmg_dist_trend": _dmg_trend,
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
                            # WG：可用激活方式与默认激活方式
                            _aam = cd.get('availableActivationModes') or []
                            if _aam:
                                _modes_zh = []
                                for _m in _aam:
                                    _mu = str(_m).upper()
                                    _modes_zh.append("手动" if _mu == "MANUAL" else ("自动" if _mu == "AUTO" else str(_m)))
                                con_detail.append(self.make_item("可用激活方式", '/'.join(_modes_zh), cd2)); cd2 += 1
                            _dam = cd.get('defaultActivationMode') or ""
                            if _dam:
                                _du = str(_dam).upper()
                                con_detail.append(self.make_item("默认激活方式", "手动" if _du == "MANUAL" else ("自动" if _du == "AUTO" else str(_dam)), cd2)); cd2 += 1
                            con_detail.append(self.make_item("消耗品效果", "", cd2, row_type="header")); cd2 += 1
                            if ct == "crashCrew":
                                con_detail.append(self.make_item("说明", "扑灭起火、清除进水、并修复受损配件。", cd2)); cd2 += 1
                            elif ct == "healForsage":
                                _mfa = pid.get('max_forsage_amount')
                                _frg = pid.get('forsage_regeneration')
                                if _mfa:
                                    con_detail.append(self.make_item("引擎加速时间", f"{_mfa:.0f}", cd2, unit="s")); cd2 += 1
                                    if _frg:
                                        con_detail.append(self.make_item("引擎加速冷却时间", f"{_mfa / _frg:.0f}", cd2, unit="s")); cd2 += 1
                                bc = cd.get('boostCoeff', 0)
                                if bc: con_detail.append(self.make_item("加速倍率", f"{bc}倍", cd2)); cd2 += 1
                            elif ct in ("callFighters", "fighter"):
                                fn = cd.get('fightersName', '')
                                if fn: con_detail.append(self.make_item("战斗机名称", self.resolve_name('plane', fn) or fn, cd2)); cd2 += 1
                                con_detail.append(self.make_item("数量", str(cd.get('fightersNum', 0)), cd2)); cd2 += 1
                                con_detail.append(self.make_item("截击机", "是" if cd.get('isInterceptor', False) else "否", cd2)); cd2 += 1
                                dog = cd.get('dogFightTime', 0); fly = cd.get('flyAwayTime', 0)
                                if isinstance(dog, dict):
                                    dog = next((x for x in dog.values() if isinstance(x, (int, float))), 0)
                                if dog: con_detail.append(self.make_item("狗斗", str(dog), cd2, unit="s")); cd2 += 1
                                if fly: con_detail.append(self.make_item("离开", str(fly), cd2, unit="s")); cd2 += 1
                                rk = cd.get('distanceToKill', 0)
                                if isinstance(rk, dict):
                                    rk = next((x for x in rk.values() if isinstance(x, (int, float))), 0)
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
                            "available_activation_modes": cd.get('availableActivationModes') or [] if cfg else [],
                            "default_activation_mode": cd.get('defaultActivationMode') or "" if cfg else "",
                            "time_based": self.is_time_based(cd) if cfg else False,
                        })
                config_contents[key] = {
                    "items": items,
                    "raw_ammo_types": raw_ammo_types,
                    "raw_consumables": raw_consumables,
                }
                if is_tactical:
                    config_contents[key]["tactical"] = True
            sub_contents[label] = {"config_labels": config_labels, "config_contents": config_contents, "config_label_map": config_label_map}

        self._aircraft_sub_info = {"舰载机": {"sub_labels": sub_labels, "sub_keys": sub_keys, "sub_contents": sub_contents}}
        return self.make_section("舰载机", [])
    def _build_air_support(self, conn, vc, ship_id, letter, result):
        # ── WG：反潜空袭模块（A_AirSupport 扁平结构）独立显示 ──
        # WG 行含 ammo_list_json/ammo_switch_coeff/fly_away_time/time_from_heaven 等 WG 特有列，
        # 与 Lesta 版（plane_name/support_type 字段）结构不同，命中 WG 数据时走独立逻辑后返回。
        try:
            _cols = {r[1] for r in conn.execute("PRAGMA table_info(ship_module_air_support)").fetchall()}
        except Exception:
            _cols = set()
        if {"ammo_list_json", "ammo_switch_coeff", "fly_away_time", "time_from_heaven"}.issubset(_cols):
            _rows = conn.execute(
                "SELECT * FROM ship_module_air_support WHERE version_code=? AND ship_id=? AND config_group LIKE ?",
                (vc, ship_id, f"{letter}%")).fetchall()
            if _rows and any(r['ammo_list_json'] or r['ammo_switch_coeff'] for r in _rows):
                self._build_wg_air_support(conn, vc, ship_id, letter, result)
                return
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
                if s.get('min_time_to_attack') is not None: items.append(self.make_item("最近到位时间", str(s['min_time_to_attack']), o, unit="s")); o += 1
                if s.get('max_time_to_attack') is not None: items.append(self.make_item("最远到位时间", str(s['max_time_to_attack']), o, unit="s")); o += 1
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
                # ── 支援机效果：伴航校射侦察机提供的友军加成 / 烟幕释放机布设的烟幕 ──
                # 作为子属性行直接并入当前支援机组卡片（不用 header，避免单独开卡片）
                if st == "scout":
                    bf = conn.execute(
                        "SELECT buff_json FROM consumable_buff WHERE buff_id='PCOM061_AirSupport_Scout' "
                        "ORDER BY buff_level DESC LIMIT 1").fetchone()
                    if bf:
                        try:
                            bmods = json.loads(bf['buff_json'] or '{}')
                        except Exception:
                            bmods = {}
                        if bmods:
                            for bk, bv in sorted(bmods.items()):
                                label = Mapping.MODIFIER_MAP.get(bk, bk)
                                if isinstance(bv, (int, float)):
                                    # 用词条方向规则上色：负方向词条（如误差减小=增益）显绿
                                    _clr = Mapping.get_modifier_color(bk, bv)
                                    items.append(self.make_item(label, f"{(bv-1)*100:+.1f}", o,
                                                                unit="%", color=_clr)); o += 1
                elif st == "smoke":
                    # 从飞机 ability_slot 找烟幕生成器消耗品配置
                    sg_id = ""
                    sg_cfg = None
                    for si in range(5):
                        sv = pid.get(f'ability_slot_{si}')
                        if not sv:
                            continue
                        parts = str(sv).split('|', 1)
                        if 'SmokeGenerator' in parts[0]:
                            sg_id = parts[0]
                            variant = parts[1] if len(parts) > 1 else ""
                            sg_cfg = conn.execute(
                                "SELECT * FROM consumable_configs WHERE version_code=? AND consumable_id=? AND config_key=?",
                                (vc, sg_id, variant)).fetchone()
                            break
                    if sg_cfg:
                        try:
                            scd = json.loads(sg_cfg['extra_json'] or '{}')
                        except Exception:
                            scd = {}
                        r = float(scd.get('radius', 0) or 0)
                        if r: items.append(self.make_item("烟幕半径", f"{r*3:.2f}", o, unit="m")); o += 1
                        h = scd.get('height', 0)
                        if h: items.append(self.make_item("烟幕高度", str(h), o, unit="m")); o += 1
                        lt = scd.get('lifeTime', 0)
                        if lt: items.append(self.make_item("烟幕持续时间", str(lt), o, unit="s")); o += 1
                        wt = scd.get('workTime', 0)
                        if wt: items.append(self.make_item("生效时间", str(wt), o, unit="s")); o += 1
                        ad = scd.get('activationDelay', 0)
                        if ad: items.append(self.make_item("生效延迟", str(ad), o, unit="s")); o += 1
                        num = scd.get('numConsumables')
                        if num is not None: items.append(self.make_item("数量", '无限' if num == -1 else str(num), o)); o += 1
                # ── 弹药数据 ──
                if arm:
                    _dmg_trend = None
                    pbi = conn.execute(
                        "SELECT species, ammo_type, custom_ui_postfix FROM projectile_basic_info WHERE version_code=? AND projectile_id=?",
                        (vc, arm)).fetchone()
                    if pbi:
                        species = pbi['species'] or ""
                        atype = pbi['ammo_type'] or ""
                        ammo_name = ammo_map.get(arm.upper(), self.resolve_name('ammo', arm) or arm)
                        # 添加弹药占位，供 _build_weapon_widget 计数用
                        items.append(self.make_item("弹药", ammo_name, o)); o += 1
                        detail_items: list[dict] = []
                        di = 0
                        _ac = "alpha_damage, bullet_krupp, alpha_piercing_he, alpha_piercing_cs, bullet_speed, explosion_radius, burn_prob, bullet_mass, bullet_diameter, bullet_air_drag, bullet_always_ricochet_at, bullet_ricochet_at, bullet_detonator, bullet_detonator_threshold, bullet_cap_normalize_max"
                        _bc = f"damage, skips_json, max_skip_angle, {_ac}"
                        for tbl, cols in [("projectile_bullet_ext", _ac), ("projectile_bomb_ext", _bc),
                                           ("projectile_rocket_ext", f"damage, {_ac}"),
                                           ("projectile_depth_charge_ext", "damage, dc_speed, dc_timer, dc_max_depth, depth_splash_size")]:
                            ext = conn.execute(f"SELECT {cols} FROM {tbl} WHERE version_code=? AND projectile_id=?", (vc, arm)).fetchone()
                            if ext:
                                ext = dict(ext)
                                if tbl == "projectile_depth_charge_ext":
                                    if ext['damage']: detail_items.append(self.make_item("标伤", f"{ext['damage']:.0f}", di)); di += 1
                                    if ext['dc_speed']: detail_items.append(self.make_item("下沉速度", f"{ext['dc_speed']:.2f}", di, unit="m/s")); di += 1
                                    if ext['dc_timer']: detail_items.append(self.make_item("引信定时", f"{ext['dc_timer']:.2f}", di, unit="s")); di += 1
                                    if ext['dc_max_depth']: detail_items.append(self.make_item("最大深度", f"{abs(ext['dc_max_depth']):.0f}", di, unit="m")); di += 1
                                    if ext['depth_splash_size']: detail_items.append(self.make_item("溅射范围", f"{ext['depth_splash_size']:.2f}", di, unit="m")); di += 1
                                else:
                                    if ext['alpha_damage']: detail_items.append(self.make_item("标伤", f"{ext['alpha_damage']:.0f}", di)); di += 1
                                    detail_items.append(self.make_item("弹种", atype, di)); di += 1
                                    if atype == "HE":
                                        if ext['alpha_piercing_he']: detail_items.append(self.make_item("穿深", f"{ext['alpha_piercing_he']:.1f}", di, unit="mm")); di += 1
                                    elif atype == "CS":
                                        if ext['alpha_piercing_cs']: detail_items.append(self.make_item("穿深", f"{ext['alpha_piercing_cs']:.1f}", di, unit="mm")); di += 1
                                    else:
                                        if ext['bullet_krupp']: detail_items.append(self.make_item("弹头硬度", f"{ext['bullet_krupp']:.0f}", di)); di += 1
                                    if ext['bullet_speed']: detail_items.append(self.make_item("弹速", f"{ext['bullet_speed']:.0f}", di, unit="m/s")); di += 1
                                    if ext['burn_prob'] is not None and atype == "HE": detail_items.append(self.make_item("起火概率", f"{ext['burn_prob']*100:.2f}", di, unit="%")); di += 1
                                    if atype in ("AP", "CS"):
                                        if ext['bullet_air_drag']: detail_items.append(self.make_item("空气阻力系数", str(ext['bullet_air_drag']), di)); di += 1
                                        if ext['bullet_diameter']: detail_items.append(self.make_item("口径", f"{ext['bullet_diameter']*1000:.2f}", di, unit="mm")); di += 1
                                        if ext['bullet_always_ricochet_at']: detail_items.append(self.make_item("强制跳弹角", f"{ext['bullet_always_ricochet_at']:.1f}", di, unit="°")); di += 1
                                        if ext['bullet_ricochet_at']: detail_items.append(self.make_item("概率跳弹角", f"{ext['bullet_ricochet_at']:.1f}", di, unit="°")); di += 1
                                        if ext['bullet_cap_normalize_max']: detail_items.append(self.make_item("弹头转正角", f"{ext['bullet_cap_normalize_max']:.1f}", di, unit="°")); di += 1
                                        if atype == "AP":
                                            if ext['bullet_detonator']: detail_items.append(self.make_item("引信长度", f"{ext['bullet_detonator']}", di, unit="s")); di += 1
                                            if ext['bullet_detonator_threshold']: detail_items.append(self.make_item("引信触发阈值", f"{ext['bullet_detonator_threshold']:.2f}", di, unit="mm")); di += 1
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
                                "SELECT alpha_damage, damage, torpedo_speed, torpedo_max_dist, torpedo_visibility, torpedo_arming_time, flood_generation, is_deep_water, deep_water_ignore_classes, distance_of_damage_json "
                                "FROM projectile_torpedo_ext WHERE version_code=? AND projectile_id=?", (vc, arm)).fetchone()
                            if te:
                                sge = conn.execute("SELECT search_radius, search_angle, max_yaw, max_vertical_speed, max_depth_level, target_lost_degradation_time FROM projectile_torpedo_sub_guidance_ext WHERE version_code=? AND projectile_id=?", (vc, arm)).fetchone()
                                is_guided = sge is not None; is_deep = te['is_deep_water']
                                if is_guided:
                                    detail_items.append(self.make_item("类型", "声呐导向鱼雷", di)); di += 1
                                    if sge['search_radius']: detail_items.append(self.make_item("搜索半径", f"{sge['search_radius']:.2f}", di, unit="km")); di += 1
                                    if sge['search_angle']: detail_items.append(self.make_item("搜索角度", f"{sge['search_angle']:.0f}", di, unit="°")); di += 1
                                    if sge['max_yaw']: detail_items.append(self.make_item("最大转向角", f"{sge['max_yaw']:.0f}", di, unit="°")); di += 1
                                    if sge['max_vertical_speed']: detail_items.append(self.make_item("最大垂直速度", f"{sge['max_vertical_speed']:.2f}", di, unit="kts")); di += 1
                                    if sge['max_depth_level']: detail_items.append(self.make_item("最大深度级别", f"{sge['max_depth_level']:.0f}", di)); di += 1
                                    if sge['target_lost_degradation_time']: detail_items.append(self.make_item("丢失目标降级时间", f"{sge['target_lost_degradation_time']:.1f}", di, unit="s")); di += 1
                                elif is_deep:
                                    detail_items.append(self.make_item("类型", "深水鱼雷", di)); di += 1
                                _dod = te['distance_of_damage_json']
                                _dmg_trend = None
                                if _dod:
                                    try:
                                        _arr = json.loads(_dod)
                                        _parts = []
                                        if isinstance(_arr, (list, tuple)) and len(_arr) >= 1:
                                            _first = _arr[0]
                                            if isinstance(_first, (list, tuple)) and len(_first) >= 2:
                                                _parts.append(f"前 {_first[0]*0.03:.2f}km 保持 {_first[1]*100:g}% 伤害")
                                            if len(_arr) >= 2:
                                                for _pair in _arr[1:-1]:
                                                    if isinstance(_pair, (list, tuple)) and len(_pair) >= 2:
                                                        _parts.append(f"到 {_pair[0]*0.03:.2f}km 渐变为 {_pair[1]*100:g}% 伤害")
                                                _last = _arr[-1]
                                                if isinstance(_last, (list, tuple)) and len(_last) >= 2:
                                                    _parts.append(f"直到 {_last[0]*0.03:.2f}km 渐变并保持 {_last[1]*100:g}% 伤害")
                                        if _parts:
                                            detail_items.append(self.make_item("动态鱼雷伤害", '\n'.join(_parts), di)); di += 1
                                        if len(_arr) >= 2 and isinstance(_arr[0], (list, tuple)) and isinstance(_arr[1], (list, tuple)) \
                                                and len(_arr[0]) >= 2 and len(_arr[1]) >= 2:
                                            _a, _b = _arr[0][1], _arr[1][1]
                                            if _a is not None and _b is not None:
                                                _dmg_trend = "increase" if _a < _b else ("decrease" if _a > _b else None)
                                    except (json.JSONDecodeError, TypeError, ValueError):
                                        pass
                                if is_deep and te['deep_water_ignore_classes']:
                                    _ignored = [x.strip() for x in te['deep_water_ignore_classes'].split(",") if x.strip() and x.strip() != "Auxiliary"]
                                    _ignored_cn = "、".join(Mapping.SHIP_CLASS_MAP.get(x, x) for x in _ignored)
                                    _all_types = ["Destroyer", "Cruiser", "Battleship", "AirCarrier", "Submarine"]
                                    _hittable_cn = "、".join(Mapping.SHIP_CLASS_MAP.get(x, x) for x in _all_types if x not in _ignored)
                                    detail_items.append(self.make_item("可攻击目标", _hittable_cn, di, color="#1b8a1b")); di += 1
                                    detail_items.append(self.make_item("无法攻击目标", _ignored_cn, di, color="#d32f2f")); di += 1
                                ad = te['alpha_damage'] or 0
                                if ad: detail_items.append(self.make_item("标伤", f"{ad * 0.33:.0f}", di)); di += 1
                                if te['torpedo_speed']: detail_items.append(self.make_item("航速", f"{te['torpedo_speed']:.0f}", di, unit="kts")); di += 1
                                if te['torpedo_max_dist'] is not None: detail_items.append(self.make_item("最大射程", f"{(te['torpedo_max_dist'] * 30) / 1000:.2f}", di, unit="km")); di += 1
                                fg = te['flood_generation'] or 0
                                if fg: detail_items.append(self.make_item("基础漏水率", f"{fg * 100:.0f}", di, unit="%")); di += 1
                        raw_ammo_types.append({
                            "ammo_id": arm, "name": ammo_name,
                            "species": species, "ammo_type": atype,
                            "raw_ammo_type": pbi['ammo_type'] if pbi else "",
                            "torpedo_postfix": pbi['custom_ui_postfix'] if pbi else "",
                            "dmg_dist_trend": _dmg_trend,
                            "detail_items": detail_items,
                        })
        if items or raw_ammo_types:
            result[letter] = {"items": items, "raw_ammo_types": raw_ammo_types}

    def _build_wg_air_support(self, conn, vc, ship_id, letter, result):
        """WG：反潜空袭模块（A_AirSupport 扁平结构）——深水炸弹等空袭显示"""
        items = []
        raw_ammo_types: list[dict] = []
        o = 0
        ammo_map = self.get_name_map("ammo")
        BUOY_LABEL = {"SURFACE": "水面", "PERISCOPE": "潜望镜深度", "DIVED": "潜航", "DEPTH": "深潜"}
        for s in conn.execute(
            "SELECT * FROM ship_module_air_support WHERE version_code=? AND ship_id=? AND config_group LIKE ?",
            (vc, ship_id, f"{letter}%")).fetchall():
            s = dict(s)
            ammo_ids: list[str] = []
            try:
                al = s.get('ammo_list_json')
                parsed = json.loads(al) if isinstance(al, str) else al
                if isinstance(parsed, list):
                    ammo_ids = [x for x in parsed if x]
            except Exception:
                ammo_ids = []
            # 空袭标题按实际携带弹药类型命名：同时有高爆炸弹+深水炸弹 → "高爆/深弹空袭"。
            # ammoList 里是飞机名，飞机 bomb_name 才是弹药名，再查 projectile 判定类型。
            def _as_kind(_a):
                _pi = conn.execute(
                    "SELECT bomb_name FROM plane_basic_info WHERE version_code=? AND plane_id=?",
                    (vc, _a)).fetchone()
                _arm = _pi['bomb_name'] if (_pi and _pi['bomb_name']) else _a
                _pbi = conn.execute(
                    "SELECT species, ammo_type FROM projectile_basic_info WHERE version_code=? AND projectile_id=?",
                    (vc, _arm)).fetchone()
                if not _pbi:
                    return ""
                _sp = _pbi['species'] or ""
                _at = _pbi['ammo_type'] or ""
                if _sp == "DepthCharge":
                    return "深弹"
                if _sp in ("bomb", "Bomb"):
                    return {"AP": "穿甲", "HE": "高爆", "SAP": "半穿甲"}.get(_at, "高爆")
                if _sp in ("rocket", "Rocket"):
                    return {"AP": "穿甲火箭", "HE": "高爆火箭"}.get(_at, "火箭")
                return ""
            _kinds: list[str] = []
            for _a in ammo_ids:
                _k = _as_kind(_a)
                if _k and _k not in _kinds:
                    _kinds.append(_k)
            if len(_kinds) >= 2:
                _header = "/".join(_kinds) + "空袭"
            elif len(_kinds) == 1:
                _header = "反潜空袭" if _kinds[0] == "深弹" else _kinds[0] + "空袭"
            else:
                _header = "反潜空袭" if ammo_ids else "空袭"
            items.append(self.make_item(_header, "", o, row_type="header")); o += 1
            if s['charges'] is not None:
                items.append(self.make_item("最大充能次数", str(s['charges']), o)); o += 1
            if s['reload_time']:
                items.append(self.make_item("装填时间", str(s['reload_time']), o, unit="s")); o += 1

            def _fmt_range(v):
                if v is None:
                    return None
                return "全图" if v == float('inf') else f"{v / 1000:.2f}"
            rtxt = _fmt_range(s['max_range'])
            rtxt2 = _fmt_range(s.get('min_range'))
            if rtxt:
                items.append(self.make_item("最大距离", rtxt, o, unit="km")); o += 1
            if rtxt2:
                items.append(self.make_item("最小距离", rtxt2, o, unit="km")); o += 1
            if s.get('fly_away_time') is not None:
                items.append(self.make_item("飞离时间", str(s['fly_away_time']), o, unit="s")); o += 1
            if s.get('time_from_heaven') is not None:
                items.append(self.make_item("天降时间", str(s['time_from_heaven']), o, unit="s")); o += 1
            asc = s.get('ammo_switch_coeff')
            if asc and len(ammo_ids) >= 2:
                # ammoSwitchCoeff 是【切换时装填系数】：实际切换装填时间 = 装填时间 × 系数。
                # 仅当 ammoList 含 2+ 种弹药（飞机）时才需切换装填，单弹药不显示。
                _sw_rt = (s.get('reload_time') or 0) * asc
                if _sw_rt:
                    items.append(self.make_item("切换装填时间", f"{_sw_rt:.1f}", o, unit="s")); o += 1
            if s.get('auto_use') is not None:
                items.append(self.make_item("自动使用", "是" if s['auto_use'] else "否", o)); o += 1
            buoy_states: list[str] = []
            bs = s.get('available_buoyancy_states_json')
            if bs:
                try:
                    _parsed = json.loads(bs) if isinstance(bs, str) else bs
                    if isinstance(_parsed, list):
                        buoy_states = [x for x in _parsed if x]
                except Exception:
                    buoy_states = []
            if buoy_states:
                items.append(self.make_item("可用浮态", " / ".join(BUOY_LABEL.get(x, x) for x in buoy_states), o)); o += 1
            # 弹药详情（深水炸弹等）。
            # ⚠️ ammo_list_json 里存的是【飞机名】（如 PAAD908_ASW_T10），
            #    飞机的 bombName（plane_basic_info.bomb_name）才是弹药名（如 PAPD107_depth_T10）
            for arm0 in ammo_ids:
                arm = arm0
                pinfo = conn.execute(
                    "SELECT plane_id, plane_index, bomb_name, species, max_speed, cruising_speed, "
                    "speed_move_with_bomb, speed_max_mult, speed_min_mult, hp, attack_count, "
                    "flight_height, attacker_size, num_planes_in_squadron, visibility_factor "
                    "FROM plane_basic_info WHERE version_code=? AND plane_id=?",
                    (vc, arm0)).fetchone()
                if pinfo:
                    arm = pinfo['bomb_name'] or arm0
                    pname = self.resolve_plane(arm0) or arm0
                    items.append(self.make_item("飞机型号", pname, o)); o += 1
                    if pinfo['speed_move_with_bomb']:
                        items.append(self.make_item("巡航速度", str(pinfo['speed_move_with_bomb']), o, unit="kts")); o += 1
                    if pinfo['attack_count']:
                        items.append(self.make_item("载弹量", str(pinfo['attack_count']), o)); o += 1
                    if pinfo['num_planes_in_squadron']:
                        items.append(self.make_item("编队飞机数", str(pinfo['num_planes_in_squadron']), o)); o += 1
                ammo_name = ammo_map.get(arm.upper(), self.resolve_name('ammo', arm) or arm)
                items.append(self.make_item("弹药", ammo_name, o)); o += 1
                detail_items: list[dict] = []
                di = 0
                if buoy_states:
                    detail_items.append(self.make_item("可用浮态", " / ".join(BUOY_LABEL.get(x, x) for x in buoy_states), di)); di += 1
                pbi = conn.execute(
                    "SELECT species, ammo_type, custom_ui_postfix FROM projectile_basic_info "
                    "WHERE version_code=? AND projectile_id=?", (vc, arm)).fetchone()
                species = pbi['species'] if pbi else ""
                atype = pbi['ammo_type'] if pbi else ""
                ext = conn.execute(
                    "SELECT damage, dc_speed, dc_timer, dc_max_depth, depth_splash_size "
                    "FROM projectile_depth_charge_ext WHERE version_code=? AND projectile_id=?", (vc, arm)).fetchone()
                if ext:
                    ext = dict(ext)
                    if ext['damage']:
                        detail_items.append(self.make_item("标伤", f"{ext['damage']:.0f}", di)); di += 1
                    if ext['dc_speed']:
                        detail_items.append(self.make_item("下沉速度", f"{ext['dc_speed']:.2f}", di, unit="m/s")); di += 1
                    if ext['dc_timer']:
                        detail_items.append(self.make_item("引信定时", f"{ext['dc_timer']:.2f}", di, unit="s")); di += 1
                    if ext['dc_max_depth']:
                        detail_items.append(self.make_item("最大深度", f"{abs(ext['dc_max_depth']):.0f}", di, unit="m")); di += 1
                    if ext['depth_splash_size']:
                        detail_items.append(self.make_item("溅射范围", f"{ext['depth_splash_size']:.2f}", di, unit="m")); di += 1
                else:
                    # 通用弹药（炸弹/火箭等）
                    bext = conn.execute(
                        "SELECT alpha_damage, alpha_piercing_he, bullet_speed, burn_prob, explosion_radius "
                        "FROM projectile_bullet_ext WHERE version_code=? AND projectile_id=?", (vc, arm)).fetchone()
                    if bext:
                        bext = dict(bext)
                        if bext['alpha_damage']:
                            detail_items.append(self.make_item("标伤", f"{bext['alpha_damage']:.0f}", di)); di += 1
                        if bext['alpha_piercing_he'] and atype == "HE":
                            detail_items.append(self.make_item("穿深", f"{bext['alpha_piercing_he']:.1f}", di, unit="mm")); di += 1
                        if bext['bullet_speed']:
                            detail_items.append(self.make_item("弹速", f"{bext['bullet_speed']:.0f}", di, unit="m/s")); di += 1
                        if bext['burn_prob'] is not None and atype == "HE":
                            detail_items.append(self.make_item("起火概率", f"{bext['burn_prob'] * 100:.2f}", di, unit="%")); di += 1
                        if bext['explosion_radius']:
                            detail_items.append(self.make_item("爆炸半径", f"{bext['explosion_radius']:.2f}", di, unit="m")); di += 1
                raw_ammo_types.append({
                    "ammo_id": arm, "name": ammo_name,
                    "species": species, "ammo_type": atype,
                    "raw_ammo_type": pbi['ammo_type'] if pbi else "",
                    "torpedo_postfix": pbi['custom_ui_postfix'] if pbi else "",
                    "dmg_dist_trend": None,
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
            # 按 header 行分组：找到 {letter} 配置 标记，将后续 items 归入该 letter
            letter_contents: dict[str, list[dict]] = {}
            letter_raw_ammo: dict[str, list[dict]] = {}
            current_letter = None
            for item in items:
                if item.get("row_type") == "header":
                    hdr = item.get("name", "")
                    for lt in letters:
                        if f"{lt} 配置" == hdr:
                            current_letter = lt
                            letter_contents.setdefault(current_letter, [])
                            break
                elif current_letter is not None:
                    letter_contents.setdefault(current_letter, []).append(item)
            if raw_ammo:
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
        其次尝试飞机名称映射，
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

        # 飞机名称映射（查 name_mappings plane 分类）
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

        # 4. 升级品数据（从 modernization_basic_info 按舰种/等级/国家/分组匹配）
        ship_type = basic['shiptype'] or ""
        ship_tier = basic['tier'] or 0
        ship_group = basic['group_status_key'] or ""
        # 查国家

        # ── 5. 信号旗数据 ────────────────────────────────
        SIGNAL_SLOTS = [
            {"key": "HPBoost", "label": "November"},
            {"key": "GM", "label": "Yankee"},
            {"key": "ATBA", "label": "Foxtrot"},
            {"key": "Speed", "label": "Sierra"},
            {"key": "Consumable", "label": "India"},
            {"key": "Shift", "label": "Charlie"},
        ]
        SIGNAL_RARITY_NAMES = {1: "标准", 2: "特殊", 3: "稀有", 4: "精英"}
        signal_slots: list[dict] = []
        num_slots = 6
        # 从数据库读取信号旗数据
        all_flags: list[dict] = []
        try:
            for row in conn.execute(
                "SELECT mod_id, name, rarity, signal_type, modifiers_json FROM signal_flags WHERE version_code=? ORDER BY rarity",
                (vc,)).fetchall():
                st = row['signal_type']
                if not (0 <= st < 6):
                    continue
                mods = json.loads(row['modifiers_json'] or '{}')
                raw_name = row['name'] or ""
                type_label = SIGNAL_SLOTS[st]["label"]
                disp_name = f"{type_label}信号旗·{SIGNAL_RARITY_NAMES.get(row['rarity'], str(row['rarity']))}"
                all_flags.append({
                    "mod_id": row['mod_id'],
                    "name": disp_name,
                    "raw_name": raw_name,
                    "rarity": row['rarity'],
                    "signalType": st,
                    "modifiers": mods,
                    "image_key": raw_name,
                })
        except Exception:
            pass
        # 如果数据库为空，直接从 JSON 文件读取（兼容旧数据库）
        if not all_flags:
            import glob as _glob
            exterior_dir = get_data_dir() / "split" / "Exterior"
            for fp in sorted(exterior_dir.glob("PCEF*.json")) if exterior_dir.exists() else []:
                try:
                    with open(fp, "r", encoding="utf-8") as fh:
                        obj = json.load(fh)
                    st = obj.get("signalType", -1)
                    if 0 <= st < 6:
                        raw_name = obj.get("name", "")
                        type_label = SIGNAL_SLOTS[st]["label"]
                        disp_name = f"{type_label}信号旗·{SIGNAL_RARITY_NAMES.get(obj.get('rarity',1), str(obj.get('rarity',1)))}"
                        all_flags.append({
                            "mod_id": obj.get("index", ""),
                            "name": disp_name,
                            "raw_name": raw_name,
                            "rarity": obj.get("rarity", 1),
                            "signalType": st,
                            "modifiers": obj.get("modifiers", {}),
                            "image_key": raw_name,
                        })
                except Exception:
                    pass
        for i in range(num_slots):
            slot_info = dict(SIGNAL_SLOTS[i])
            slot_info["slot_idx"] = i
            slot_info["flags"] = [f for f in all_flags if f["signalType"] == i]
            signal_slots.append(slot_info)

        # ── WG：14 种信号旗同时显示（PCEF010 无加成属性，不显示）──
        # 名称取本地化（IDS_PCEFxxx_*_SIGNALFLAG），未命中回退 raw name
        wg_flags: list[dict] = []
        for row in conn.execute(
            "SELECT mod_id, name, rarity, modifiers_json, flags_json "
            "FROM signal_flags WHERE version_code=? ORDER BY mod_id", (vc,)).fetchall():
            mid = row['mod_id']
            if mid.startswith("PCEF010"):
                continue  # PCEF010 无加成，不在应用内显示
            mods = json.loads(row['modifiers_json'] or '{}')
            if not mods:
                continue
            raw_name = row['name'] or ""
            disp = self.resolve_name("signal_flag", raw_name) or raw_name
            wg_flags.append({
                "mod_id": mid,
                "name": disp,
                "raw_name": raw_name,
                "modifiers": mods,
                "flags": json.loads(row['flags_json'] or '[]'),
                "image_key": raw_name,
            })

        nat_row = conn.execute(
            "SELECT nation FROM entity_registry WHERE version_code=? AND entity_id=?",
            (vc, ship_id)).fetchone()
        ship_nation = nat_row[0] if nat_row else ""
        from models.name_mapping import Mapping as NM2
        modernizations: list[dict] = []
        for r in conn.execute(
            "SELECT mod_id, name, slot, rarity, modifiers_json, groups_json, ships_json, "
            "excludes_json, nations_json, shiptype_json, shiplevel_json "
            "FROM modernization_basic_info WHERE version_code=? AND slot>=0 ORDER BY slot, rarity, sort_index",
            (vc,)).fetchall():
            slot = r['slot']
            mod_id = r['mod_id']
            ships = json.loads(r['ships_json'] or '[]')
            excludes = json.loads(r['excludes_json'] or '[]')
            types = json.loads(r['shiptype_json'] or '[]')
            levels = json.loads(r['shiplevel_json'] or '[]')
            nations = json.loads(r['nations_json'] or '[]')
            groups = json.loads(r['groups_json'] or '[]')
            modifiers = json.loads(r['modifiers_json'] or '{}')
            rarity = r['rarity']
            # 匹配条件：
            # - ships_json：若非空，作为额外包含列表；若它是唯一正面条件则变为排他
            # - types/levels/nations/groups：均为 AND 条件，非空时必须匹配
            # - 若所有正面条件均为空 → 不可安装
            has_any_positive = bool(ships or groups or nations or types or levels)
            if not has_any_positive:
                matched = False
            elif ship_id in excludes:
                matched = False
            elif ships and not groups and not nations and not types and not levels:
                # ships_json 是唯一正面条件 → 排他：必须在列表中
                matched = ship_id in ships
            elif ships and ship_id in ships:
                # ships_json 包含该船 → 直接通过
                matched = True
            else:
                # 按 type/level/nation/group（AND 逻辑）匹配
                matched = True
                if types and ship_type not in types:
                    matched = False
                if levels and ship_tier not in levels:
                    matched = False
                if nations and ship_nation not in nations:
                    matched = False
                if groups and ship_group not in groups:
                    matched = False
            if matched:
                dname = self.resolve_name('modernization', mod_id) or mod_id
                modernizations.append({
                    "mod_id": mod_id,
                    "name": dname,
                    "slot": slot,
                    "rarity": rarity,
                    "modifiers": modifiers,
                })

        # 5. 升级信息（ShipUpgradeInfo），解析模块名称（保留用于模块按钮）
        # 按 prev 字段排序：无 prev 的在前，有 prev 的跟在对应 key 后面
        rows = conn.execute(
            "SELECT upgrade_key, uc_type, components_json, prev FROM ship_upgrade_info "
            "WHERE version_code=? AND ship_id=?",
            (vc, ship_id)).fetchall()
        upgrade_map: dict[str, dict] = {}
        for r in rows:
            upgrade_map[r["upgrade_key"]] = {
                "key": r["upgrade_key"],
                "type": r["uc_type"],
                "prev": r["prev"] or "",
                "comps": json.loads(r["components_json"] or "{}"),
            }
        upgrades: list[dict] = []
        # 按类型分组排序
        types_order = ["_Hull", "_Engine", "_Artillery", "_Suo", "_Torpedoes",
                       "_Sonar",
                       "_Fighter", "_DiveBomber", "_TorpedoBomber", "_SkipBomber", "_MineBomber", "_FlightControl"]
        for ut in types_order:
            group = {k: v for k, v in upgrade_map.items() if v["type"] == ut}
            if not group:
                continue
            # 拓扑排序：无 prev 的排前面，有 prev 的跟在后面
            sorted_group: list[dict] = []
            remaining = dict(group)
            while remaining:
                # 找当前无前置或前置已排序的
                for k, v in list(remaining.items()):
                    if not v["prev"] or v["prev"] not in remaining:
                        sorted_group.append(v)
                        del remaining[k]
            for ug in sorted_group:
                comps = ug["comps"]
                resolved_comps: dict[str, list[dict]] = {}
                for slot_type, mods in comps.items():
                    resolved_mods = []
                    for mid in mods:
                        display_name = self._resolve_module_display_name(mid)
                        resolved_mods.append({"id": mid, "name": display_name})
                    resolved_comps[slot_type] = resolved_mods
                upgrades.append({
                    "key": ug["key"],
                    "key_name": self._resolve_module_display_name(ug["key"]),
                    "type": ug["type"],
                    "components": resolved_comps,
                })

        # 6. 舰船基本信息摘要
        from models.name_mapping import Mapping as NM2
        nation_name = ""
        nat_row = conn.execute(
            "SELECT nation FROM entity_registry WHERE version_code=? AND entity_id=?",
            (vc, ship_id)).fetchone()
        if nat_row:
            nation_name = NM2.NATION_MAP.get(nat_row[0], nat_row[0])

        # 确定默认（stock）配置字母：找 hull 类型中无 prev 的升级
        _stock_config_letter = "A"
        for ug in upgrades:
            if ug["type"] == "_Hull":
                for slot_type, mods in ug["components"].items():
                    if slot_type == "hull" and mods:
                        mid = mods[0]["id"]
                        _stock_config_letter = mid[0] if mid else "A"
                        break
                break

        return {
            "nation": nation_name,
            "tier": basic['tier'],
            "ship_id": ship_id,
            "shiptype": self.resolve_enum("ship_class", basic['shiptype']) if basic['shiptype'] else "",
            "shiptype_en": basic['shiptype'] or "",
            "group_status": basic['group_status_key'] or "",
            "module_groups": module_groups,
            "engine": engine_name,
            "consumables": consumables,
            "upgrades": upgrades,
            "modernizations": modernizations,
            "signal_slots": signal_slots,
            "signal_flags": wg_flags,
            "_stock_config_letter": _stock_config_letter,
        }
