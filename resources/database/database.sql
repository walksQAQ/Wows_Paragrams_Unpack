-- =====================================================================
-- 战舰数据分析器系统 - 纯结构化合并落盘级数据库架构 (Pure Structured Schema)
-- =====================================================================
--
-- 架构调整说明:
--   - 彻底移除了所有表中的 `raw_json`、`_json` 后缀的文本字段。
--   - 数据不再存储任何形式的原始 raw data，写入时必须由各 Analyzer 模块深度解析后分块落盘。
--   - 复杂的动态字段（如 modifiers, dynamic attributes）改用实体扩展属性关联表实现。
-- =====================================================================

PRAGMA foreign_keys = ON;

-- ═════════════════════════════════════════════════════════════════════
-- 1. 本地化层 (Localization)
-- ═════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS name_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,       -- 'ship','ammo','gun','consumable','modernization','plane','rage_mode'
    key_name TEXT NOT NULL,       -- 原始 Key 保持大写 (如 'PASA002', 'IDS_PJSB018')
    lang_zh TEXT NOT NULL,        -- 中文翻译
    UNIQUE(category, key_name)
);
CREATE INDEX IF NOT EXISTS idx_mappings_lookup ON name_mappings(category, key_name);

CREATE TABLE IF NOT EXISTS po_translations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    msgid TEXT NOT NULL UNIQUE,   -- 原始 msgid
    msgstr TEXT NOT NULL,         -- 中文翻译
    context TEXT DEFAULT ''        
);

CREATE TABLE IF NOT EXISTS enum_translations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    enum_type TEXT NOT NULL,       -- 'nation','ship_class','ship_group','weapon_species'
    enum_key TEXT NOT NULL,        -- 原始枚举值 (如 "USA", "Destroyer")
    lang_zh TEXT NOT NULL,         -- 中文翻译
    UNIQUE(enum_type, enum_key)
);


-- ═════════════════════════════════════════════════════════════════════
-- 2. 核心注册层 (Registration & Identity Only)
--    无原始数据（No Raw Data），仅作为系统内唯一种群索引的生命周期管理总表
-- ═════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS entity_registry (
    entity_id TEXT PRIMARY KEY,                       -- 统一的编号/Index
    entity_type TEXT NOT NULL,                        -- 'ship','gun','projectile','plane','consumable','modernization','crew'
    nation TEXT,                                      -- 国家编码
    shiptype TEXT,                                    -- 船种编码
    tier INTEGER                                      -- 等级
);
CREATE INDEX IF NOT EXISTS idx_registry_filter ON entity_registry(entity_type, nation, shiptype, tier);


-- ═════════════════════════════════════════════════════════════════════
-- 3. 通用动态多态属性子表 (取代各类 _json 字段)
-- ═════════════════════════════════════════════════════════════════════

-- 用于替代原先各大表中散落的各种 `extra_json`, `modifiers_json`, `trigger_json` 
CREATE TABLE IF NOT EXISTS entity_dynamic_attributes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id TEXT NOT NULL REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
    scope TEXT NOT NULL,           -- 作用域：'consumable_extra', 'rage_trigger', 'rage_modifier', 'crew_effect', 'submarine_torp'
    attr_key TEXT NOT NULL,        -- 属性项名 (如 'hp_regeneration_rate', 'critical_chance')
    attr_value TEXT,               -- 结构化字符值
    attr_value_num REAL,           -- 数值型标量（如有，便于范围SQL筛选查询）
    UNIQUE(entity_id, scope, attr_key)
);
CREATE INDEX IF NOT EXISTS idx_dynamic_attr_lookup ON entity_dynamic_attributes(entity_id, scope);


-- ═════════════════════════════════════════════════════════════════════
-- 4. 分析结构化层 (Structured Analysis Tables)
-- ═════════════════════════════════════════════════════════════════════
--
-- 注意：以下是所有「舰船相关」的数据表定义，以 ship_ 为前缀。
-- 重构时应重点关注此区块，其他区块（gun_ / projectile_ / plane_ /
-- consumable_ / modernization_ / crew_）与舰船数据松耦合，可作为
-- 独立实体表保留。
--
-- ┌─────────────────────────────────────────────────────────────┐
-- │  🚢 舰船相关表清单（共 14 张表 + 1 张桥接表）              │
-- │                                                            │
-- │  4a-01  ship_basic_info         舰船基础属性                │
-- │  4a-02  ship_consumable_slots   舰船消耗品槽位              │
-- │  4a-03  ship_rage_mode          舰船战斗指令                │
-- │  4a-04  ship_module_hulls       舰船船体模块                │
-- │  4a-05  ship_sub_depth_states   潜艇深度状态（依赖 hulls）  │
-- │  4a-06  ship_module_artillery   主炮模块                    │
-- │  4a-07  ship_module_atba        副炮模块                    │
-- │  4a-08  ship_module_torpedoes   鱼雷模块                    │
-- │  4a-09  ship_module_aa          防空模块                    │
-- │  4a-10  ship_module_depth_charge 深水炸弹模块               │
-- │  4a-11  ship_module_aircraft    舰载机模块                  │
-- │  4a-12  ship_module_hangar      机库模块                    │
-- │  4a-13  ship_module_air_support 空袭模块                    │
-- │  4a-14  ship_module_mapping     模块字母→子分类映射         │
-- │                                                            │
-- │  桥接表 (跨实体):                                           │
-- │  rel_ship_weapon_ammo          武器←→弹药关联              │
-- └─────────────────────────────────────────────────────────────┘
-- --------------------------------------------------------------------
-- 4a. 战舰深度拆分结构 (Ship Data Shards)  【重构目标区块】
-- --------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ship_basic_info (
    ship_id TEXT PRIMARY KEY REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
    ship_name_zh TEXT,
    ship_index TEXT,
    ship_id_num INTEGER,
    nation_zh TEXT,
    shiptype_zh TEXT,
    tier_display TEXT,
    group_status TEXT,
    parent_ship_name TEXT,
    origin_ship_name TEXT
);

CREATE TABLE IF NOT EXISTS ship_consumable_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ship_id TEXT NOT NULL REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
    slot_index INTEGER NOT NULL,
    item_index INTEGER NOT NULL,
    display_name TEXT,
    type TEXT,
    num_consumables TEXT,
    preparation_time REAL,
    work_time REAL,
    reload_time REAL,
    is_auto_consumable INTEGER DEFAULT 0,
    consumable_id TEXT DEFAULT '',             -- 消耗品 ID（file_key），用于关联 consumable_basic_info
    config_key TEXT DEFAULT 'Default',         -- 消耗品子配置键（如 'Default'、'Ping'）
    UNIQUE(ship_id, slot_index, item_index)
);

CREATE TABLE IF NOT EXISTS ship_rage_mode (
    ship_id TEXT PRIMARY KEY REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
    display_name TEXT,
    boost_duration REAL,
    max_activation_count TEXT,
    is_auto_usage INTEGER DEFAULT 0,
    is_modifier_works_always INTEGER DEFAULT 0,
    decrement_delay REAL,
    decrement_period REAL,
    decrement_count REAL,
    description_ids TEXT DEFAULT '',
    modifiers_json TEXT DEFAULT '{}',
    triggers_json TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS ship_module_hulls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ship_id TEXT NOT NULL REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
    module_letter TEXT NOT NULL,
    hull_key TEXT NOT NULL,
    health REAL,
    max_speed REAL,
    turning_radius REAL,
    rudder_time REAL,
    conceal_sea REAL,
    conceal_air REAL,
    has_citadel INTEGER DEFAULT 0,
    hull_regen_part REAL,
    citadel_regen_part REAL,
    engine_power REAL,
    has_battery INTEGER DEFAULT 0,
    battery_capacity REAL,
    battery_regen REAL,
    has_hydrophone INTEGER DEFAULT 0,
    hydrophone_radius REAL,
    hydrophone_update_freq REAL,
    hydrophone_work_states TEXT,
    hydrophone_detect_states TEXT,
    buoyancy_rudder_time REAL,
    max_buoyancy_speed REAL,
    UNIQUE(ship_id, hull_key)
);

-- 潜艇深度状态分块表（取代旧潜艇字段中的 depth_data_json 文本）
CREATE TABLE IF NOT EXISTS ship_sub_depth_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hull_ref_id INTEGER NOT NULL REFERENCES ship_module_hulls(id) ON DELETE CASCADE,
    state_name TEXT NOT NULL,       -- 'surface', 'periscope', 'deep'
    underwater_max_speed REAL,
    buoyancy_burn_rate REAL,
    visibility_factor REAL,
    UNIQUE(hull_ref_id, state_name)
);

CREATE TABLE IF NOT EXISTS ship_module_artillery (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ship_id TEXT NOT NULL REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
    module_letter TEXT NOT NULL,
    gun_name TEXT,
    count INTEGER,
    num_barrels INTEGER,
    reload_time REAL,
    max_range REAL,
    sigma REAL,
    dispersion_formula TEXT,
    radius_zero REAL,
    radius_delim REAL,
    radius_max REAL,
    delim REAL,
    special_mode_name TEXT,                     -- 如有 F 联动、爆发射击等
    drum_shots_count INTEGER DEFAULT 0,        -- 弹鼓/弹夹每轮射击数 (shotsCount)
    drum_shot_delay REAL DEFAULT 0,            -- 弹鼓/弹夹射速间隔 (shotDelay)
    drum_full_reload_time REAL DEFAULT 0,      -- 弹鼓/弹夹完整装填时间 (fullReloadTime)
    drum_is_switchable INTEGER DEFAULT 0,      -- 是否可切换模式
    drum_is_chargeable INTEGER DEFAULT 0,      -- 是否可充能
    drum_charge_time_min REAL DEFAULT 0,       -- 充能时间下限
    drum_charge_time_max REAL DEFAULT 0,       -- 充能时间上限
    drum_charge_mode INTEGER DEFAULT 0,        -- 充能模式 (chargeTimeParams[2])
    drum_modifiers_json TEXT DEFAULT '{}',      -- 弹鼓模式修正参数
    UNIQUE(ship_id, module_letter, gun_name)
);

CREATE TABLE IF NOT EXISTS ship_module_atba (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ship_id TEXT NOT NULL REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
    module_letter TEXT NOT NULL,
    gun_name TEXT,
    count INTEGER,
    num_barrels INTEGER,
    reload_time REAL,
    max_range REAL,
    sigma REAL,
    dispersion_formula TEXT,
    radius_zero REAL,
    radius_delim REAL,
    radius_max REAL,
    delim REAL,
    UNIQUE(ship_id, module_letter, gun_name)
);

CREATE TABLE IF NOT EXISTS ship_module_torpedoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ship_id TEXT NOT NULL REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
    module_letter TEXT NOT NULL,
    launcher_name TEXT,
    count INTEGER,
    num_barrels INTEGER,
    reload_time REAL,
    UNIQUE(ship_id, module_letter, launcher_name)
);

-- 模块与弹药解析映射绑定桥接物理表 (彻底废除了多张武器表的 ammo_list_json)
CREATE TABLE IF NOT EXISTS rel_ship_weapon_ammo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    weapon_type TEXT NOT NULL,         -- 'artillery', 'atba', 'torpedo'
    weapon_ref_id INTEGER NOT NULL,    -- 对应上面具体模块表的物理自增 id
    ammo_id TEXT NOT NULL,             -- 对应的弹药投射物 ID
    UNIQUE(weapon_type, weapon_ref_id, ammo_id)
);

CREATE TABLE IF NOT EXISTS ship_module_aa (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ship_id TEXT NOT NULL REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
    module_letter TEXT NOT NULL,
    aura_name TEXT,
    aura_type TEXT,
    aura_dps REAL,
    bubble_damage REAL,
    aa_gun_name TEXT,
    aa_gun_count INTEGER,
    UNIQUE(ship_id, module_letter, aura_name, aa_gun_name)
);

CREATE TABLE IF NOT EXISTS ship_module_depth_charge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ship_id TEXT NOT NULL REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
    module_letter TEXT NOT NULL,
    gun_name TEXT,
    count INTEGER,
    UNIQUE(ship_id, module_letter, gun_name)
);

CREATE TABLE IF NOT EXISTS ship_module_aircraft (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ship_id TEXT NOT NULL REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
    module_letter TEXT NOT NULL,
    module_variant TEXT DEFAULT '',
    plane_name TEXT,
    armament_name TEXT,
    UNIQUE(ship_id, module_letter, module_variant, plane_name)
);

CREATE TABLE IF NOT EXISTS ship_module_hangar (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ship_id TEXT NOT NULL REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
    module_letter TEXT NOT NULL,
    deck_place_count INTEGER,
    plane_reserve_capacity INTEGER,
    launchpad_type TEXT,
    launch_prepare_time REAL,
    is_parallel_launch INTEGER DEFAULT 0,
    joint_launch_count INTEGER,
    joint_launch_delay REAL,
    hangar_hp REAL,
    hangar_regen_part REAL,
    air_support_squadrons INTEGER,
    UNIQUE(ship_id, module_letter)
);

CREATE TABLE IF NOT EXISTS ship_module_air_support (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ship_id TEXT NOT NULL REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
    module_letter TEXT NOT NULL,
    plane_name TEXT,
    charges INTEGER,
    reload_time REAL,
    work_time REAL,
    max_range REAL,
    min_range REAL,
    armament_name TEXT,
    UNIQUE(ship_id, module_letter, plane_name)
);

CREATE TABLE IF NOT EXISTS ship_module_mapping (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ship_id TEXT NOT NULL REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
    module_letter TEXT NOT NULL,          -- 模块字母：A, B, C...
    sub_category TEXT NOT NULL,           -- 子分类：'船体','主炮','副炮','鱼雷','防空','深水炸弹','舰载机','机库','空袭'
    source_key TEXT DEFAULT '',           -- 来源原始 JSON key 示例（如 'A_Hull','B_Artillery'），仅供参考
    display_order INTEGER DEFAULT 0,     -- 该子分类在此字母模块中的排序
    UNIQUE(ship_id, module_letter, sub_category)
);


-- --------------------------------------------------------------------
-- 4b. 火炮结构化分析 (Gun Analysis)
-- --------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS gun_basic_info (
    gun_id TEXT PRIMARY KEY REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
    gun_name_zh TEXT,
    gun_index TEXT,
    gun_id_num INTEGER,
    weapon_species TEXT,
    num_barrels INTEGER,
    caliber REAL,
    reload_time REAL,
    rotation_speed_h REAL,
    rotation_speed_v REAL,
    max_health REAL,
    auto_repair_time REAL,
    torpedo_angles TEXT,
    time_between_shots REAL,
    ideal_radius REAL,
    min_radius REAL,
    ideal_distance REAL,
    radius_zero REAL,
    radius_delim REAL,
    radius_max REAL,
    delim REAL,
    dispersion_formula TEXT
);

-- 弹夹火炮连发细节（取代旧表 drum_params_json）
CREATE TABLE IF NOT EXISTS gun_drum_details (
    gun_id TEXT PRIMARY KEY REFERENCES gun_basic_info(gun_id) ON DELETE CASCADE,
    clip_size INTEGER,
    clip_reload_time REAL,
    burst_count INTEGER,
    burst_reload_time REAL
);

CREATE TABLE IF NOT EXISTS gun_ammo_list (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gun_id TEXT NOT NULL REFERENCES gun_basic_info(gun_id) ON DELETE CASCADE,
    ammo_id TEXT NOT NULL,
    ammo_name_zh TEXT,
    UNIQUE(gun_id, ammo_id)
);


-- --------------------------------------------------------------------
-- 4c. 弹药/投射物纯结构化分析 (Projectile Analysis)
-- --------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS projectile_basic_info (
    projectile_id TEXT PRIMARY KEY REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
    ammo_name_zh TEXT,
    projectile_index TEXT,
    projectile_id_num INTEGER,
    nation_zh TEXT,
    species TEXT,
    ammo_type TEXT,
    alpha_damage REAL,
    bullet_mass REAL,
    bullet_speed REAL,
    bullet_krupp REAL,
    alpha_piercing_he REAL,
    burn_prob REAL,
    explosion_radius REAL,
    bullet_always_ricochet_at REAL,
    bullet_ricochet_at REAL,
    bullet_detonator REAL,
    bullet_detonator_threshold REAL,
    bullet_air_drag REAL,
    bullet_diameter REAL,
    bullet_cap_normalize_max REAL,
    torpedo_type TEXT,
    is_deep_water INTEGER DEFAULT 0,
    torpedo_max_dist REAL,
    torpedo_speed REAL,
    torpedo_visibility REAL,
    torpedo_arming_time REAL,
    torpedo_uw_critical REAL,
    ignore_classes TEXT,
    dc_speed REAL,
    dc_timer REAL,
    dc_max_depth REAL,
    attack_sequence_durations TEXT,
    wave_max_damage_pct REAL,
    wave_min_damage_pct REAL,
    wave_speed REAL,
    wave_sector TEXT,
    laser_heat REAL,
    laser_heat_radius REAL,
    laser_damage_types TEXT,
    damage REAL,
    alpha_piercing_cs REAL,
    depth_splash_size REAL,
    depth_splash_size_to_torpedo REAL,
    custom_ui_postfix TEXT,
    extra_json TEXT DEFAULT '{}'
);


-- --------------------------------------------------------------------
-- 4d. 飞机结构化分析 (Plane Analysis)
-- --------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS plane_basic_info (
    plane_id TEXT PRIMARY KEY REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
    plane_name_zh TEXT,
    plane_index TEXT,
    tier INTEGER,
    nation_zh TEXT,
    aircraft_class TEXT,
    cruise_speed REAL,
    max_speed REAL,
    min_speed REAL,
    max_health REAL,
    squadron_health REAL,
    restore_time REAL,
    deck_capacity INTEGER,
    squadron_size INTEGER,
    attack_size INTEGER,
    attack_count INTEGER,
    bomb_drop_delay REAL,
    preparation_time REAL,
    aiming_time REAL,
    armament_name TEXT,
    armament_name_zh TEXT
);

CREATE TABLE IF NOT EXISTS plane_ability_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plane_id TEXT NOT NULL REFERENCES plane_basic_info(plane_id) ON DELETE CASCADE,
    slot_index INTEGER NOT NULL,
    ability_id TEXT,
    ability_limit INTEGER,
    UNIQUE(plane_id, slot_index)
);


-- --------------------------------------------------------------------
-- 4e. 消耗品结构化分析 (Consumable Analysis)
-- --------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS consumable_basic_info (
    consumable_id TEXT PRIMARY KEY REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
    display_name TEXT,
    consumable_index TEXT,
    consumable_id_num INTEGER
);

-- 消耗品子配置表：每个词条（如 B_Gold / Default_Gold）独立一行，可按 config_key 精确查询
CREATE TABLE IF NOT EXISTS consumable_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    consumable_id TEXT NOT NULL REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
    config_key TEXT NOT NULL,              -- 子配置键名，如 'B_Gold', 'Default', 'Ping'
    consumable_type TEXT,
    num_consumables TEXT,
    work_time REAL,
    preparation_time REAL,
    reload_time REAL,
    is_auto_consumable INTEGER DEFAULT 0,
    is_interceptor INTEGER DEFAULT 0,
    regen_hp_speed REAL,
    area_dmg_multiplier REAL,
    bubble_dmg_multiplier REAL,
    fighter_name TEXT,
    fighter_num INTEGER,
    available_buoyancy_states TEXT,        -- JSON 列表：可用深度状态
    extra_json TEXT DEFAULT '{}',
    UNIQUE(consumable_id, config_key)
);


-- --------------------------------------------------------------------
-- 4f. 升级品结构化分析 (Modernization Analysis)
-- --------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS modernization_basic_info (
    mod_id TEXT PRIMARY KEY REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
    mod_name_zh TEXT,
    mod_index TEXT,
    mod_id_num INTEGER,
    cost_cr INTEGER,
    slot TEXT
);

CREATE TABLE IF NOT EXISTS modernization_modifiers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mod_id TEXT NOT NULL REFERENCES modernization_basic_info(mod_id) ON DELETE CASCADE,
    modifier_key TEXT NOT NULL,
    modifier_name_zh TEXT,
    modifier_value TEXT,
    formatted_value TEXT,
    UNIQUE(mod_id, modifier_key)
);

CREATE TABLE IF NOT EXISTS modernization_restrictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mod_id TEXT NOT NULL REFERENCES modernization_basic_info(mod_id) ON DELETE CASCADE,
    restriction_type TEXT NOT NULL,
    restriction_value TEXT NOT NULL
);


-- --------------------------------------------------------------------
-- 4g. 技能/舰长结构化分析 (Crew Analysis)
-- --------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS crew_basic_info (
    crew_id TEXT PRIMARY KEY REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
    crew_name TEXT,
    crew_index TEXT,
    nation_zh TEXT,
    is_unique INTEGER DEFAULT 0,
    is_animated INTEGER DEFAULT 0,
    is_elite INTEGER DEFAULT 0,
    is_person INTEGER DEFAULT 0,
    is_retrainable INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS crew_unique_skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    crew_id TEXT NOT NULL REFERENCES crew_basic_info(crew_id) ON DELETE CASCADE,
    skill_key TEXT NOT NULL,
    trigger_type TEXT,
    trigger_type_name_zh TEXT,
    max_trigger_num INTEGER,
    trigger_achievement TEXT,
    trigger_damage_num REAL,
    trigger_damage_type TEXT,
    damage_percent_threshold REAL,
    trigger_ribbons_num INTEGER,
    trigger_ribbon_types TEXT,
    trigger_allowed_ships TEXT,
    effects_json TEXT DEFAULT '{}',
    UNIQUE(crew_id, skill_key)
);


-- ═════════════════════════════════════════════════════════════════════
-- 5. 统一分析映射视图层 (Unified Index Views)
-- ═════════════════════════════════════════════════════════════════════

DROP VIEW IF EXISTS v_all_entities;
CREATE VIEW v_all_entities AS
SELECT entity_id, entity_type, nation, shiptype, tier FROM entity_registry;

DROP VIEW IF EXISTS v_analyzed_entities;
CREATE VIEW v_analyzed_entities AS
SELECT entity_id, entity_type,
    CASE entity_type
        WHEN 'ship' THEN (SELECT ship_name_zh FROM ship_basic_info WHERE ship_id = entity_id)
        WHEN 'gun' THEN (SELECT gun_name_zh FROM gun_basic_info WHERE gun_id = entity_id)
        WHEN 'projectile' THEN (SELECT ammo_name_zh FROM projectile_basic_info WHERE projectile_id = entity_id)
        WHEN 'plane' THEN (SELECT plane_name_zh FROM plane_basic_info WHERE plane_id = entity_id)
    END AS display_name
FROM entity_registry;


-- ═════════════════════════════════════════════════════════════════════
-- 6. 数据版本控制元数据 (Metadata)
-- ═════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS meta_schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS meta_game_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_version TEXT NOT NULL,
    wows_type TEXT NOT NULL DEFAULT '',
    bin_folder TEXT DEFAULT '',
    entity_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);