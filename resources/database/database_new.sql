PRAGMA foreign_keys = ON;

-- ═════════════════════════════════════════════════════════════════════
-- 0. 版本控制中心 (Version Control Registry)
--    全库生命周期起点。删除某个 version_code 时，ON DELETE CASCADE
--    自动级联清除该版本下所有数据。
-- ═════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS data_version_registry (
    version_id INTEGER PRIMARY KEY AUTOINCREMENT,    -- 自增版本 ID（数值序，用于滚动判断）
    version_code TEXT NOT NULL UNIQUE,                -- 版本代号 (如 '13.1', '13.2', '26.6.1.0')
    wows_type TEXT DEFAULT '',                        -- 服务器类型 (如 'Lesta', 'Wargaming')
    bin_folder TEXT DEFAULT '',                       -- 游戏 bin 子版本号
    entity_count INTEGER DEFAULT 0,                   -- 该版本的实体总数
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 滚动剪枝索引：快速定位最旧版本
CREATE INDEX IF NOT EXISTS idx_version_seq ON data_version_registry(version_id);


-- ═════════════════════════════════════════════════════════════════════
-- 1. 本地化层 (Localization)  — 不绑定 version_code，跨版本共享
-- ═════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS name_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,       -- 'ship','ammo','gun','consumable','modernization','plane','rage_mode','crew'
    key_name TEXT NOT NULL,       -- 原始 Key 保持大写 (如 'PASA002', 'IDS_PJSB018')
    lang_zh TEXT NOT NULL,        -- 中文翻译
    UNIQUE(category, key_name)
);

CREATE TABLE IF NOT EXISTS enum_translations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    enum_type TEXT NOT NULL,       -- 'nation','ship_class','ship_group','weapon_species'
    enum_key TEXT NOT NULL,        -- 原始枚举值 (如 "USA", "Destroyer")
    lang_zh TEXT NOT NULL,         -- 中文翻译
    UNIQUE(enum_type, enum_key)
);


-- ═════════════════════════════════════════════════════════════════════
-- 2. 核心注册层 (Registration & Identity)
--    version_code 揉进联合主键，确保版本隔离 + 级联斩首
-- ═════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS entity_registry (
    version_code TEXT NOT NULL REFERENCES data_version_registry(version_code) ON DELETE CASCADE,
    entity_id TEXT NOT NULL,                           -- 统一的编号/Index (如 'PASA002', 'PAPB002')
    entity_type TEXT NOT NULL,                         -- 'ship','gun','projectile','plane','consumable','modernization','crew'
    nation TEXT,                                       -- 国家编码
    PRIMARY KEY (version_code, entity_id)
);
CREATE INDEX IF NOT EXISTS idx_registry_filter ON entity_registry(version_code, entity_type, nation);


-- ═════════════════════════════════════════════════════════════════════
-- 3. 舰船基础信息层 (Ship Basic Info)
-- ═════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS ship_basic_info (
    version_code TEXT NOT NULL,
    ship_id TEXT NOT NULL,
    name_mapping_id INTEGER REFERENCES name_mappings(id),
    shiptype TEXT,                    -- 舰船类型
    tier INTEGER,                     -- 舰船等级
    ship_index TEXT,                  -- 舰船编号
    ship_id_num INTEGER,              -- 舰船 ID
    group_status_key TEXT,            -- → enum_translations (如 'upgradeable','premium')
    parent_ship_id TEXT,              -- 原型舰船 entity_id（跨版本）
    origin_ship_id TEXT,              -- 原型舰船名称 entity_id
    PRIMARY KEY (version_code, ship_id),
    FOREIGN KEY (version_code, ship_id) REFERENCES entity_registry(version_code, entity_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ship_module_relations (
    version_code TEXT NOT NULL,
    ship_id TEXT NOT NULL,
    module_id TEXT NOT NULL,              -- 模块 entity_id（如 gun/projectile 等注册实体）
    slot_type TEXT NOT NULL,              -- 组件大类: 'artillery','engine','fire_control','torpedoes','airDefense','hull','atba','specials'
    config_group TEXT NOT NULL,           -- 对应原始 JSON 的键前缀 (如 'AB1','A','B')
    mount_count INTEGER DEFAULT 1,        -- 挂载点数量
    PRIMARY KEY (version_code, ship_id, module_id, slot_type, config_group),
    FOREIGN KEY (version_code, ship_id) REFERENCES ship_basic_info(version_code, ship_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_ship_rel_lookup ON ship_module_relations(version_code, ship_id, config_group);


-- ═════════════════════════════════════════════════════════════════════
-- 3a. 舰船模块信息层 (Ship Module Info)
--     所有表均以 (version_code, ship_id, config_group, module_key) 为骨架
-- ═════════════════════════════════════════════════════════════════════

-- 1. 船体组件属性表
CREATE TABLE IF NOT EXISTS ship_module_hulls (
    version_code TEXT NOT NULL,
    ship_id TEXT NOT NULL,
    config_group TEXT NOT NULL,
    module_key TEXT NOT NULL,             -- 模块 key (如 'A_Hull','B_Hull')
    health REAL,                         -- 模块血量
    max_speed REAL,                      -- 最大航速 (kts)
    turning_radius REAL,                 -- 转弯半径 (m)
    rudder_time REAL,                    -- 转舵时间 (s)
    conceal_sea REAL,                    -- 水面隐蔽 (km)
    conceal_air REAL,                    -- 空中隐蔽 (km)
    visibility_factor_by_plane REAL,     -- 被飞机发现距离 (km)
    has_citadel INTEGER DEFAULT 0,       -- 是否有核心区
    hull_regen_part REAL,                -- 船体恢复比例
    citadel_regen_part REAL,             -- 核心恢复比例
    engine_power REAL,                   -- 引擎马力 (hp)
    PRIMARY KEY (version_code, ship_id, config_group, module_key),
    FOREIGN KEY (version_code, ship_id) REFERENCES ship_basic_info(version_code, ship_id) ON DELETE CASCADE
);

-- 1a. 船体组件额外扩增表 (潜艇专用)
CREATE TABLE IF NOT EXISTS ship_module_hulls_ext (
    version_code TEXT NOT NULL,
    ship_id TEXT NOT NULL,
    config_group TEXT NOT NULL,
    module_key TEXT NOT NULL,
    battery_capacity REAL,               -- 潜艇电池容量
    battery_regen REAL,                  -- 电池恢复速率
    hydrophone_radius REAL,              -- 水听器探测半径 (km)
    hydrophone_update_freq REAL,         -- 水听器更新频率
    hydrophone_work_states TEXT,         -- 水听器可用深度状态 (JSON)
    hydrophone_detect_states TEXT,       -- 水听器可探测深度状态 (JSON)
    buoyancy_rudder_time REAL,           -- 水平舵转舵时间
    max_buoyancy_speed REAL,             -- 最大上浮/下潜速度
    PRIMARY KEY (version_code, ship_id, config_group, module_key),
    FOREIGN KEY (version_code, ship_id, config_group, module_key) REFERENCES ship_module_hulls(version_code, ship_id, config_group, module_key) ON DELETE CASCADE
);

-- 1b. 潜艇深度状态分块表
CREATE TABLE IF NOT EXISTS ship_sub_depth_states (
    version_code TEXT NOT NULL,
    ship_id TEXT NOT NULL,
    config_group TEXT NOT NULL,
    module_key TEXT NOT NULL,
    state_name TEXT NOT NULL,            -- 'surface'(水面),'periscope'(潜望镜),'deep'(深潜)
    underwater_max_speed REAL,           -- 该深度最大航速
    buoyancy_burn_rate REAL,             -- 每秒电量消耗率
    visibility_factor REAL,              -- 隐蔽系数
    PRIMARY KEY (version_code, ship_id, config_group, module_key, state_name),
    FOREIGN KEY (version_code, ship_id, config_group, module_key) REFERENCES ship_module_hulls_ext(version_code, ship_id, config_group, module_key) ON DELETE CASCADE
);

-- 2. 主炮组件属性表
CREATE TABLE IF NOT EXISTS ship_module_artillery (
    version_code TEXT NOT NULL,
    ship_id TEXT NOT NULL,
    config_group TEXT NOT NULL,
    module_key TEXT NOT NULL,
    count INTEGER,                       -- 同型号炮塔数量
    num_barrels INTEGER,                 -- 每座联装数
    reload_time REAL,                    -- 装填时间 (s)
    max_range REAL,                      -- 最大射程 (km)
    sigma REAL,                          -- 精度 Sigma
    rotation_speed_h REAL,               -- 水平回转速度 (°/s)
    rotation_speed_v REAL,               -- 垂直回转速度 (°/s)
    ideal_radius REAL,                   -- 散布理想半径
    min_radius REAL,                     -- 散布最小半径
    ideal_distance REAL,                 -- 散布理想距离
    radius_zero REAL,                    -- 散布 0 距离系数
    radius_delim REAL,                   -- 散布分界系数
    radius_max REAL,                     -- 散布最大系数
    delim REAL,                          -- 散布分界点
    PRIMARY KEY (version_code, ship_id, config_group, module_key),
    FOREIGN KEY (version_code, ship_id) REFERENCES ship_basic_info(version_code, ship_id) ON DELETE CASCADE
);

-- 2a. 主炮特殊模式扩增表 (弹鼓/充能/F键)
-- 注：module_key 加入主键和外键以匹配 ship_module_artillery 的完整 PK
CREATE TABLE IF NOT EXISTS ship_module_artillery_ext (
    version_code TEXT NOT NULL,
    ship_id TEXT NOT NULL,
    config_group TEXT NOT NULL,
    module_key TEXT NOT NULL,             -- 对应 ship_module_artillery.module_key
    special_mode_name TEXT,
    drum_shots_count INTEGER DEFAULT 0,
    drum_shot_delay REAL DEFAULT 0,
    drum_full_reload_time REAL DEFAULT 0,
    drum_is_switchable INTEGER DEFAULT 0,
    drum_is_chargeable INTEGER DEFAULT 0,
    drum_charge_time_min REAL DEFAULT 0,
    drum_charge_time_max REAL DEFAULT 0,
    drum_charge_mode INTEGER DEFAULT 0,
    drum_modifiers_json TEXT DEFAULT '{}',
    PRIMARY KEY (version_code, ship_id, config_group, module_key),
    FOREIGN KEY (version_code, ship_id, config_group, module_key) REFERENCES ship_module_artillery(version_code, ship_id, config_group, module_key) ON DELETE CASCADE
);

-- 3. 副炮组件属性表
CREATE TABLE IF NOT EXISTS ship_module_atba (
    version_code TEXT NOT NULL,
    ship_id TEXT NOT NULL,
    config_group TEXT NOT NULL,
    module_key TEXT NOT NULL,
    count INTEGER,
    num_barrels INTEGER,
    reload_time REAL,
    max_range REAL,
    sigma REAL,
    rotation_speed_h REAL,
    rotation_speed_v REAL,
    ideal_radius REAL,
    min_radius REAL,
    ideal_distance REAL,
    radius_zero REAL,
    radius_delim REAL,
    radius_max REAL,
    delim REAL,
    PRIMARY KEY (version_code, ship_id, config_group, module_key),
    FOREIGN KEY (version_code, ship_id) REFERENCES ship_basic_info(version_code, ship_id) ON DELETE CASCADE
);

-- 4. 鱼雷组件属性表
CREATE TABLE IF NOT EXISTS ship_module_torpedoes (
    version_code TEXT NOT NULL,
    ship_id TEXT NOT NULL,
    config_group TEXT NOT NULL,
    module_key TEXT NOT NULL,
    count INTEGER,
    num_barrels INTEGER,
    reload_time REAL,
    rotation_speed REAL,
    torpedo_angles TEXT,                 -- JSON 如 ["/-60","60"]
    PRIMARY KEY (version_code, ship_id, config_group, module_key),
    FOREIGN KEY (version_code, ship_id) REFERENCES ship_basic_info(version_code, ship_id) ON DELETE CASCADE
);

-- 5. 防空炮组件属性表
CREATE TABLE IF NOT EXISTS ship_module_aa (
    version_code TEXT NOT NULL,
    ship_id TEXT NOT NULL,
    config_group TEXT NOT NULL,
    module_key TEXT NOT NULL,
    aura_name TEXT,
    type TEXT,
    aura_type TEXT,
    aura_dps REAL,
    bubble_damage REAL,
    explosion_count REAL,
    hit_chance REAL,
    max_distance REAL,
    min_distance REAL,
    aa_gun_name TEXT,
    aa_gun_count INTEGER,
    PRIMARY KEY (version_code, ship_id, config_group, module_key, aura_name, aa_gun_name),
    FOREIGN KEY (version_code, ship_id) REFERENCES ship_basic_info(version_code, ship_id) ON DELETE CASCADE
);

-- 6. 深弹组件属性表
CREATE TABLE IF NOT EXISTS ship_module_depth_charge (
    version_code TEXT NOT NULL,
    ship_id TEXT NOT NULL,
    config_group TEXT NOT NULL,
    module_key TEXT NOT NULL,
    gun_name TEXT,
    count INTEGER,
    reload_time REAL,
    shot_delay REAL,
    max_packs INTEGER,
    num_shots INTEGER,
    num_bombs INTEGER,
    projectile_id TEXT,
    damage REAL,
    dc_speed REAL,
    dc_timer REAL,
    dc_max_depth REAL,
    depth_splash_size REAL,
    PRIMARY KEY (version_code, ship_id, config_group, module_key),
    FOREIGN KEY (version_code, ship_id) REFERENCES ship_basic_info(version_code, ship_id) ON DELETE CASCADE
);

-- 7. 中队飞机组件属性表
CREATE TABLE IF NOT EXISTS ship_module_aircraft (
    version_code TEXT NOT NULL,
    ship_id TEXT NOT NULL,
    config_group TEXT NOT NULL,
    module_key TEXT NOT NULL,
    module_variant TEXT DEFAULT '',
    plane_type TEXT DEFAULT '',          -- 'Fighter','DiveBomber','TorpedoBomber','SkipBomber'
    plane_name TEXT,
    armament_name TEXT,
    PRIMARY KEY (version_code, ship_id, config_group, module_key, module_variant, plane_name),
    FOREIGN KEY (version_code, ship_id) REFERENCES ship_basic_info(version_code, ship_id) ON DELETE CASCADE
);

-- 8. 支援飞机组件属性表
CREATE TABLE IF NOT EXISTS ship_module_air_support (
    version_code TEXT NOT NULL,
    ship_id TEXT NOT NULL,
    config_group TEXT NOT NULL,
    module_key TEXT NOT NULL,
    plane_name TEXT,
    charges INTEGER,
    reload_time REAL,
    work_time REAL,
    max_range REAL,
    min_range REAL,
    armament_name TEXT,
    support_type TEXT,
    PRIMARY KEY (version_code, ship_id, config_group, module_key),
    FOREIGN KEY (version_code, ship_id) REFERENCES ship_basic_info(version_code, ship_id) ON DELETE CASCADE
);

-- 9. 引擎组件属性表
CREATE TABLE IF NOT EXISTS ship_module_engine (
    version_code TEXT NOT NULL,
    ship_id TEXT NOT NULL,
    config_group TEXT NOT NULL,
    module_key TEXT NOT NULL,
    engine_type TEXT,
    engine_power REAL,
    forward_max_speed REAL,
    backward_max_speed REAL,
    forward_forsage_power REAL,
    backward_forsage_power REAL,
    PRIMARY KEY (version_code, ship_id, config_group, module_key),
    FOREIGN KEY (version_code, ship_id) REFERENCES ship_basic_info(version_code, ship_id) ON DELETE CASCADE
);

-- 10. 战斗指令属性表
CREATE TABLE IF NOT EXISTS ship_rage_mode (
    version_code TEXT NOT NULL,
    ship_id TEXT NOT NULL,
    display_name_id INTEGER REFERENCES name_mappings(id),
    boost_duration REAL,
    max_activation_count TEXT,
    is_auto_usage INTEGER DEFAULT 0,
    is_modifier_works_always INTEGER DEFAULT 0,
    decrement_delay REAL,
    decrement_period REAL,
    decrement_count REAL,
    description_id INTEGER REFERENCES name_mappings(id),
    rage_mode_name TEXT DEFAULT '',      -- 战斗指令原始名称（用于本地化回退）
    modifiers_json TEXT DEFAULT '{}',
    triggers_json TEXT DEFAULT '[]',
    PRIMARY KEY (version_code, ship_id),
    FOREIGN KEY (version_code, ship_id) REFERENCES ship_basic_info(version_code, ship_id) ON DELETE CASCADE
);

-- 11. 舰船消耗品槽位表
CREATE TABLE IF NOT EXISTS ship_consumable_slots (
    version_code TEXT NOT NULL,
    ship_id TEXT NOT NULL,
    slot_index INTEGER NOT NULL,
    item_index INTEGER NOT NULL,
    display_name_id INTEGER REFERENCES name_mappings(id),
    consumable_id TEXT DEFAULT '',
    config_key TEXT DEFAULT 'Default',
    PRIMARY KEY (version_code, ship_id, slot_index, item_index),
    FOREIGN KEY (version_code, ship_id) REFERENCES ship_basic_info(version_code, ship_id) ON DELETE CASCADE
);


-- ═════════════════════════════════════════════════════════════════════
-- 3b. 武器模块配套弹药信息层 (Weapon Module Ammo Info)
-- ═════════════════════════════════════════════════════════════════════

-- 弹药-武器关联桥接表
-- FK 列顺序必须与 ship_module_relations 的 PK 完全一致：
-- (version_code, ship_id, module_id, slot_type, config_group)
CREATE TABLE IF NOT EXISTS ship_weapon_projectiles (
    version_code TEXT NOT NULL,
    ship_id TEXT NOT NULL,
    module_id TEXT NOT NULL,          -- → entity_registry.entity_id
    slot_type TEXT NOT NULL,          -- 'artillery' | 'atba' | 'torpedo'
    config_group TEXT NOT NULL,       -- 对应 ship_module_relations.config_group
    ammo_id TEXT NOT NULL,            -- → projectile_basic_info.projectile_id
    ammo_order INTEGER DEFAULT 0,
    PRIMARY KEY (version_code, ship_id, module_id, slot_type, config_group, ammo_id),
    FOREIGN KEY (version_code, ship_id, module_id, slot_type, config_group)
        REFERENCES ship_module_relations(version_code, ship_id, module_id, slot_type, config_group)
        ON DELETE CASCADE
);

-- 弹药基础信息表
CREATE TABLE IF NOT EXISTS projectile_basic_info (
    version_code TEXT NOT NULL,
    projectile_id TEXT NOT NULL,
    projectile_index TEXT,
    projectile_id_num INTEGER,
    species TEXT,                    -- 'Artillery','Torpedo','DepthCharge','Sonar','Rocket','Bomb'
    ammo_type TEXT,                  -- 'HE','AP','SAP','StandardTorpedo','DeepWaterTorpedo'
    custom_ui_postfix TEXT,
    PRIMARY KEY (version_code, projectile_id),
    FOREIGN KEY (version_code, projectile_id) REFERENCES entity_registry(version_code, entity_id) ON DELETE CASCADE
);

-- 2a. 炮弹属性扩增表 (species='Artillery')
CREATE TABLE IF NOT EXISTS projectile_bullet_ext (
    version_code TEXT NOT NULL,
    projectile_id TEXT NOT NULL,
    alpha_damage REAL,
    bullet_mass REAL,
    bullet_speed REAL,
    bullet_diameter REAL,
    bullet_air_drag REAL,
    bullet_krupp REAL,
    alpha_piercing_he REAL,
    explosion_radius REAL,
    burn_prob REAL,
    alpha_piercing_cs REAL,
    bullet_always_ricochet_at REAL,
    bullet_ricochet_at REAL,
    bullet_detonator REAL,
    bullet_detonator_threshold REAL,
    bullet_cap_normalize_max REAL,
    PRIMARY KEY (version_code, projectile_id),
    FOREIGN KEY (version_code, projectile_id) REFERENCES projectile_basic_info(version_code, projectile_id) ON DELETE CASCADE
);

-- 2b. 鱼雷属性扩增表 (species='Torpedo')
CREATE TABLE IF NOT EXISTS projectile_torpedo_ext (
    version_code TEXT NOT NULL,
    projectile_id TEXT NOT NULL,
    bullet_diameter REAL,
    alpha_damage REAL,
    damage REAL,
    flood_generation INTEGER DEFAULT 1,
    affected_by_ptz INTEGER DEFAULT 0,
    apply_ptz_coeff INTEGER DEFAULT 0,
    torpedo_max_dist REAL,
    torpedo_speed REAL,
    torpedo_visibility REAL,
    alert_dist REAL,                 -- 强制发现警报距离
    torpedo_arming_time REAL,
    burn_prob REAL DEFAULT 0,            -- 热能鱼雷点火率
    uw_critical REAL DEFAULT 0,          -- 基础漏水率（uwCritical, 0~1）
    is_deep_water INTEGER DEFAULT 0,
    deep_water_ignore_classes TEXT,
    PRIMARY KEY (version_code, projectile_id),
    FOREIGN KEY (version_code, projectile_id) REFERENCES projectile_basic_info(version_code, projectile_id) ON DELETE CASCADE
);

-- 2b-a. 潜艇声呐导向鱼雷扩增表
CREATE TABLE IF NOT EXISTS projectile_torpedo_sub_guidance_ext (
    version_code TEXT NOT NULL,
    projectile_id TEXT NOT NULL,
    search_radius REAL,
    search_angle REAL,
    max_depth_level REAL,
    max_vertical_speed REAL,
    max_yaw REAL,
    target_lost_degradation_time REAL,
    drop_dist_aircarrier REAL,
    drop_dist_battleship REAL,
    drop_dist_cruiser REAL,
    drop_dist_destroyer REAL,
    drop_dist_submarine REAL,
    drop_dist_default REAL,
    PRIMARY KEY (version_code, projectile_id),
    FOREIGN KEY (version_code, projectile_id) REFERENCES projectile_torpedo_ext(version_code, projectile_id) ON DELETE CASCADE
);

-- 2c. 深水炸弹属性扩增表 (species='DepthCharge')
CREATE TABLE IF NOT EXISTS projectile_depth_charge_ext (
    version_code TEXT NOT NULL,
    projectile_id TEXT NOT NULL,
    damage REAL,
    dc_speed REAL,
    dc_timer REAL,
    dc_max_depth REAL,
    depth_splash_size REAL,
    depth_splash_size_to_torpedo REAL,
    PRIMARY KEY (version_code, projectile_id),
    FOREIGN KEY (version_code, projectile_id) REFERENCES projectile_basic_info(version_code, projectile_id) ON DELETE CASCADE
);

-- 2d. 声呐波属性扩增表 (species='Sonar')
CREATE TABLE IF NOT EXISTS projectile_sonar_wave_ext (
    version_code TEXT NOT NULL,
    projectile_id TEXT NOT NULL,
    wave_speed REAL,
    wave_max_damage_pct REAL,
    wave_min_damage_pct REAL,
    wave_sector TEXT,
    attack_sequence_durations TEXT,
    laser_heat REAL,
    laser_heat_radius REAL,
    laser_damage_types TEXT,
    PRIMARY KEY (version_code, projectile_id),
    FOREIGN KEY (version_code, projectile_id) REFERENCES projectile_basic_info(version_code, projectile_id) ON DELETE CASCADE
);

-- 2e. 火箭弹属性扩增表 (species='Rocket')  — 物理分表，彻底消灭 NULL
CREATE TABLE IF NOT EXISTS projectile_rocket_ext (
    version_code TEXT NOT NULL,
    projectile_id TEXT NOT NULL,
    alpha_damage REAL,
    damage REAL,
    bullet_mass REAL,
    bullet_speed REAL,
    bullet_diameter REAL,
    bullet_air_drag REAL,
    alpha_piercing_he REAL,
    burn_prob REAL,
    explosion_radius REAL,
    alpha_piercing_cs REAL,
    attack_sequence_durations TEXT,    -- 连发攻击时间轴 JSON
    -- AP 火箭弹动态穿深
    bullet_krupp REAL,
    bullet_always_ricochet_at REAL,
    bullet_ricochet_at REAL,
    bullet_detonator REAL,
    bullet_detonator_threshold REAL,
    bullet_cap_normalize_max REAL,
    PRIMARY KEY (version_code, projectile_id),
    FOREIGN KEY (version_code, projectile_id) REFERENCES projectile_basic_info(version_code, projectile_id) ON DELETE CASCADE
);

-- 2f. 航空炸弹属性扩增表 (species='Bomb')  — 物理分表，彻底消灭 NULL
CREATE TABLE IF NOT EXISTS projectile_bomb_ext (
    version_code TEXT NOT NULL,
    projectile_id TEXT NOT NULL,
    alpha_damage REAL,
    damage REAL,
    bullet_mass REAL,
    bullet_speed REAL,
    bullet_diameter REAL,
    bullet_air_drag REAL,
    alpha_piercing_he REAL,
    burn_prob REAL,
    explosion_radius REAL,
    alpha_piercing_cs REAL,
    is_bomb INTEGER DEFAULT 1,
    flight_time_coef REAL,
    -- 跳弹轰炸机 (Skip Bomb) 专属
    skip_effect TEXT,
    max_skip_angle REAL,              -- 最大弹跳触发角度
    skips_json TEXT,                   -- 跳跃减速矩阵 JSON
    -- AP 航弹动态穿深
    bullet_krupp REAL,
    bullet_always_ricochet_at REAL,
    bullet_ricochet_at REAL,
    bullet_detonator REAL,
    bullet_detonator_threshold REAL,
    bullet_cap_normalize_max REAL,
    PRIMARY KEY (version_code, projectile_id),
    FOREIGN KEY (version_code, projectile_id) REFERENCES projectile_basic_info(version_code, projectile_id) ON DELETE CASCADE
);

-- ═════════════════════════════════════════════════════════════════════
-- 3c. 消耗品组件信息层 (Consumable Module Info)
-- ═════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS consumable_basic_info (
    version_code TEXT NOT NULL,
    consumable_id TEXT NOT NULL,
    consumable_index TEXT,
    consumable_id_num INTEGER,
    PRIMARY KEY (version_code, consumable_id),
    FOREIGN KEY (version_code, consumable_id) REFERENCES entity_registry(version_code, entity_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS consumable_configs (
    version_code TEXT NOT NULL,
    consumable_id TEXT NOT NULL,
    config_key TEXT NOT NULL,
    consumable_type TEXT,
    extra_json TEXT DEFAULT '{}',
    PRIMARY KEY (version_code, consumable_id, config_key),
    FOREIGN KEY (version_code, consumable_id) REFERENCES consumable_basic_info(version_code, consumable_id) ON DELETE CASCADE
);


-- ═════════════════════════════════════════════════════════════════════
-- 3c. 飞机属性表 (Aircraft)
-- ═════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS plane_basic_info (
    version_code TEXT NOT NULL,
    plane_id TEXT NOT NULL,
    plane_index TEXT,
    plane_id_num INTEGER,
    species TEXT,                      -- 'Fighter','Dive','Bomber','SkipBomber','Scout','TorpedoBomber'
    nation TEXT,
    plane_level INTEGER,
    max_speed REAL,
    cruising_speed REAL,
    hp REAL,
    attack_count INTEGER,
    attack_cooldown REAL,
    attack_interval REAL,
    arrange_size INTEGER,
    can_destroy INTEGER DEFAULT 1,
    can_stop INTEGER DEFAULT 0,
    bomb_name TEXT,
    -- 速度
    speed_move_with_bomb REAL,
    speed_max_mult REAL,
    speed_min_mult REAL,
    -- 角度
    angle_of_climb REAL,
    angle_of_dive REAL,
    attack_angle REAL,
    -- 散布/缩圈/时间
    preparation_time REAL,
    preparation_accel_increase REAL,
    preparation_accel_decrease REAL,
    aiming_time REAL,
    aiming_accel_increase REAL,
    aiming_accel_decrease REAL,
    flight_height REAL,
    -- 编队/燃料
    attacker_size INTEGER,
    num_planes_in_squadron INTEGER,
    fuel_time REAL,
    max_forsage_amount REAL,
    -- 机库
    hangar_max_value INTEGER,
    hangar_start_value INTEGER,
    hangar_restore_amount INTEGER,
    hangar_time_to_restore REAL,
    -- 散布椭圆
    outer_salvo_size_x REAL,
    outer_salvo_size_y REAL,
    inner_salvo_size_x REAL,
    inner_salvo_size_y REAL,
    max_spread_x REAL,
    max_spread_y REAL,
    min_spread_x REAL,
    min_spread_y REAL,
    max_spread REAL,                   -- 单值散布（鱼雷轰炸机等）
    min_spread REAL,                   -- 单值散布（鱼雷轰炸机等）
    inner_bombs_percentage REAL,
    visibility_factor REAL,              -- 飞机被侦测距离
    skip_height REAL,                     -- 跳弹轰炸机：弹跳高度/距离
    aiming_height REAL,                   -- 跳弹轰炸机：瞄准视角基准高度
    post_attack_invulnerability_duration REAL,
    ability_slot_0 TEXT,
    ability_slot_1 TEXT,
    ability_slot_2 TEXT,
    ability_slot_3 TEXT,
    ability_slot_4 TEXT,
    PRIMARY KEY (version_code, plane_id),
    FOREIGN KEY (version_code, plane_id) REFERENCES entity_registry(version_code, entity_id) ON DELETE CASCADE
);


-- ═════════════════════════════════════════════════════════════════════
-- 4. 技能/舰长结构化分析 (Crew Analysis)
-- ═════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS crew_basic_info (
    version_code TEXT NOT NULL,
    crew_id TEXT NOT NULL,
    display_name_id INTEGER REFERENCES name_mappings(id),
    crew_index TEXT,
    crew_id_num INTEGER,
    person_name TEXT,
    nation TEXT,
    is_unique INTEGER DEFAULT 0,
    is_person INTEGER DEFAULT 0,
    is_elite INTEGER DEFAULT 0,
    is_animated INTEGER DEFAULT 0,
    is_retrainable INTEGER DEFAULT 0,
    skills_container TEXT,
    base_training_level INTEGER DEFAULT 1,
    PRIMARY KEY (version_code, crew_id),
    FOREIGN KEY (version_code, crew_id) REFERENCES entity_registry(version_code, entity_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS crew_unique_skills (
    version_code TEXT NOT NULL,
    crew_id TEXT NOT NULL,
    skill_key TEXT NOT NULL,
    sort_index INTEGER DEFAULT 0,
    trigger_type TEXT,
    max_trigger_num INTEGER,
    trigger_achievement TEXT,
    trigger_damage_num REAL,
    trigger_damage_type TEXT,
    damage_percent_threshold REAL,
    trigger_ribbons_num INTEGER,
    trigger_ribbon_types TEXT,
    trigger_is_sub_ribbons INTEGER DEFAULT 0,
    trigger_join_ribbons INTEGER DEFAULT 0,
    trigger_allowed_ships TEXT,
    effects_json TEXT DEFAULT '{}',
    PRIMARY KEY (version_code, crew_id, skill_key),
    FOREIGN KEY (version_code, crew_id) REFERENCES crew_basic_info(version_code, crew_id) ON DELETE CASCADE
);


-- ═════════════════════════════════════════════════════════════════════
-- 5. 统一分析映射视图层 (Unified Index Views)
-- ═════════════════════════════════════════════════════════════════════

DROP VIEW IF EXISTS v_all_entities;
CREATE VIEW v_all_entities AS
SELECT version_code, entity_id, entity_type, nation FROM entity_registry;

DROP VIEW IF EXISTS v_analyzed_entities;
CREATE VIEW v_analyzed_entities AS
SELECT er.version_code, er.entity_id, er.entity_type,
    CASE er.entity_type
        WHEN 'ship' THEN (SELECT nm.lang_zh FROM ship_basic_info sb
                           JOIN name_mappings nm ON nm.id = sb.name_mapping_id
                           WHERE sb.ship_id = er.entity_id AND sb.version_code = er.version_code)
        WHEN 'crew' THEN (SELECT nm.lang_zh FROM crew_basic_info cb
                           JOIN name_mappings nm ON nm.id = cb.display_name_id
                           WHERE cb.crew_id = er.entity_id AND cb.version_code = er.version_code)
    END AS display_name
FROM entity_registry er;


-- ═════════════════════════════════════════════════════════════════════
-- 6. Schema 版本记录 (Meta)
-- ═════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS modernization_basic_info (
    version_code TEXT NOT NULL,
    mod_id TEXT NOT NULL,
    mod_index TEXT,
    mod_id_num INTEGER,
    name TEXT,
    cost_cr INTEGER DEFAULT 0,
    slot INTEGER DEFAULT 0,
    rarity INTEGER DEFAULT 0,
    sort_index INTEGER DEFAULT 0,
    modifiers_json TEXT DEFAULT '{}',
    excludes_json TEXT DEFAULT '[]',
    ships_json TEXT DEFAULT '[]',
    groups_json TEXT DEFAULT '[]',
    nations_json TEXT DEFAULT '[]',
    shiptype_json TEXT DEFAULT '[]',
    shiplevel_json TEXT DEFAULT '[]',
    tags_json TEXT DEFAULT '[]',
    PRIMARY KEY (version_code, mod_id)
);

CREATE TABLE IF NOT EXISTS meta_schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT DEFAULT (datetime('now','localtime'))
);
