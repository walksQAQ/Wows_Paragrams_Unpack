-- assets_data.db 表结构（3D 查看器缓存库）
-- 数据由「加载数据」时从当前客户端 assets.bin 预提取入库
-- （services/assets_cache_service.py 的 populate），3D 查看器只从本库读取。
-- 加载方式：按服务器选子目录（resources.qrc :/resources/database/lesta/assets_database.sql）→ 文件系统回退。

CREATE TABLE IF NOT EXISTS meta (
    bin_folder TEXT PRIMARY KEY,
    game_version TEXT,
    wows_type TEXT,
    created_at TEXT
);

-- 舰体/模型骨架的 HP_ 挂点（解码后：坐标 pos / 方向四元数 quat / 缩放 scale，行主序渲染空间）
CREATE TABLE IF NOT EXISTS skeleton_mounts (
    bin_folder TEXT NOT NULL,
    stem TEXT NOT NULL,
    hp_name TEXT NOT NULL,
    pos_x REAL NOT NULL DEFAULT 0,
    pos_y REAL NOT NULL DEFAULT 0,
    pos_z REAL NOT NULL DEFAULT 0,
    rot_qx REAL NOT NULL DEFAULT 0,
    rot_qy REAL NOT NULL DEFAULT 0,
    rot_qz REAL NOT NULL DEFAULT 0,
    rot_qw REAL NOT NULL DEFAULT 1,
    scale_x REAL NOT NULL DEFAULT 1,
    scale_y REAL NOT NULL DEFAULT 1,
    scale_z REAL NOT NULL DEFAULT 1,
    PRIMARY KEY(bin_folder, stem, hp_name)
);
CREATE INDEX IF NOT EXISTS idx_skel_stem ON skeleton_mounts(bin_folder, stem);

-- 完整骨骼（bind pose 按 parent 累积）解码后数据：坐标 pos / 方向四元数 quat / 缩放 scale
-- （引用小零件定位 / Root_BlendBone / 显示与其它功能直接调用，无需再分解矩阵）
CREATE TABLE IF NOT EXISTS skeleton_bones (
    bin_folder TEXT NOT NULL,
    stem TEXT NOT NULL,
    bone_name TEXT NOT NULL,
    pos_x REAL NOT NULL DEFAULT 0,
    pos_y REAL NOT NULL DEFAULT 0,
    pos_z REAL NOT NULL DEFAULT 0,
    rot_qx REAL NOT NULL DEFAULT 0,
    rot_qy REAL NOT NULL DEFAULT 0,
    rot_qz REAL NOT NULL DEFAULT 0,
    rot_qw REAL NOT NULL DEFAULT 1,
    scale_x REAL NOT NULL DEFAULT 1,
    scale_y REAL NOT NULL DEFAULT 1,
    scale_z REAL NOT NULL DEFAULT 1,
    PRIMARY KEY(bin_folder, stem, bone_name)
);
CREATE INDEX IF NOT EXISTS idx_bones_stem ON skeleton_bones(bin_folder, stem);

-- visual 渲染集：shape(.vertices) → 材质 / mfm / 是否损伤网格
-- skinned: 该渲染集是否蒙皮（Korabli 渲染集项 +0x0C）
-- nodes:   蒙皮调色板节点名 JSON 数组（+0x0D nodes_count / +0x28 item-relative relptr）
CREATE TABLE IF NOT EXISTS render_sets (
    bin_folder TEXT NOT NULL,
    geom_path TEXT NOT NULL,
    shape TEXT NOT NULL,
    material TEXT NOT NULL DEFAULT '',
    mfm TEXT NOT NULL DEFAULT '',
    damage INTEGER NOT NULL DEFAULT 0,
    skinned INTEGER NOT NULL DEFAULT 0,
    nodes TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(bin_folder, geom_path, shape)
);
CREATE INDEX IF NOT EXISTS idx_rs_geom ON render_sets(bin_folder, geom_path);

-- 材质 diffuseMap 贴图原始路径（只存路径，字节渲染时实时从客户端 pkg 解包）
CREATE TABLE IF NOT EXISTS mfm_textures (
    bin_folder TEXT NOT NULL,
    mfm_path TEXT NOT NULL,
    texture_path TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(bin_folder, mfm_path)
);

-- 材质完整信息：shader_id / 技术族 / 全部贴图原始路径(JSON) / INDEXED vec4 数组(JSON)
CREATE TABLE IF NOT EXISTS material_full (
    bin_folder TEXT NOT NULL,
    mfm_path TEXT NOT NULL,
    shader_id TEXT NOT NULL DEFAULT '0x0',
    family TEXT NOT NULL DEFAULT '',
    material_hash TEXT NOT NULL DEFAULT '',
    textures TEXT NOT NULL DEFAULT '',
    indexed TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(bin_folder, mfm_path)
);

-- *.vertices 名字哈希 → 名字（LOD/crack 兜底跳过用；populate 时从 assets.bin 字符串表
-- 提取入库，显示时只从本库读取，绝不现场读 assets.bin）
CREATE TABLE IF NOT EXISTS shape_names (
    bin_folder TEXT NOT NULL,
    hash INTEGER NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY(bin_folder, hash)
);
CREATE INDEX IF NOT EXISTS idx_sn_bin ON shape_names(bin_folder);

-- schema 版本记录（与 database_new.sql 的 meta_schema_version 规则一致：
-- 低版本时 initialize 重建全表，随后记录当前版本号）
CREATE TABLE IF NOT EXISTS meta_schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 涂装/外观（Exterior JSON 索引，数据源 data/split/Exterior/*.json）：species 区分类别
-- （Camouflage/皮肤/Decal/旗帜等）；parts/custom 等按 JSON 存，供涂装切换器按索引查询。
CREATE TABLE IF NOT EXISTS exteriors (
    version_code TEXT NOT NULL,
    ext_index    TEXT NOT NULL,
    name         TEXT NOT NULL,
    camouflage   TEXT NOT NULL DEFAULT '',
    species      TEXT NOT NULL DEFAULT '',
    nation       TEXT NOT NULL DEFAULT '',
    cost_gold    INTEGER DEFAULT 0,
    can_buy      INTEGER DEFAULT 0,
    parts_json   TEXT DEFAULT '[]',
    custom_json  TEXT DEFAULT '{}',
    unpeculiar_camouflage TEXT DEFAULT '',
    color_scheme_id INTEGER DEFAULT 0,
    icon_path    TEXT DEFAULT '',
    display_name TEXT DEFAULT '',
    data_json    TEXT DEFAULT '{}',
    PRIMARY KEY(version_code, ext_index)
);
CREATE INDEX IF NOT EXISTS idx_exteriors ON exteriors(version_code, species);

-- camouflages.xml 条目（包根，含 shipgroups/colorschemes/camouflages 三段），按索引 name
-- 查询贴图/UV/船组/目标舰。
CREATE TABLE IF NOT EXISTS camouflages (
    version_code TEXT NOT NULL,
    name         TEXT NOT NULL,
    realm        TEXT NOT NULL DEFAULT '',
    tiled        INTEGER DEFAULT 0,
    use_color_scheme INTEGER DEFAULT 0,
    color_scheme TEXT DEFAULT '',
    textures_json TEXT DEFAULT '{}',
    uv_json      TEXT DEFAULT '{}',
    ship_groups_json TEXT DEFAULT '[]',
    target_ships_json TEXT DEFAULT '[]',
    icon_path    TEXT DEFAULT '',
    display_name TEXT DEFAULT '',
    PRIMARY KEY(version_code, name)
);

-- colorschemes.xml 颜色方案（color0..3 各 4 float，JSON）
CREATE TABLE IF NOT EXISTS camouflage_color_schemes (
    version_code TEXT NOT NULL,
    name         TEXT NOT NULL,
    color0 TEXT, color1 TEXT, color2 TEXT, color3 TEXT,
    PRIMARY KEY(version_code, name)
);

-- shipgroups.xml 全局船组映射（组名 → 船 index），供涂装切换器判断某 camo 是否命中某船
CREATE TABLE IF NOT EXISTS camo_ship_groups (
    version_code TEXT NOT NULL,
    group_name  TEXT NOT NULL,
    ship        TEXT NOT NULL,
    PRIMARY KEY(version_code, group_name, ship)
);

-- 涂装选项图缓存：拆出的预览缩略图文件存 data/camo_thumbs/，本表只记录路径/尺寸/来源贴图
-- （避免每次涂装切换都重新拆图）。texture_tag 标识预览用的部件贴图（默认 tile 主贴图）。
CREATE TABLE IF NOT EXISTS camo_thumbs (
    version_code TEXT NOT NULL,
    camo_name    TEXT NOT NULL,
    texture_tag  TEXT NOT NULL DEFAULT 'tile',
    thumb_path   TEXT NOT NULL DEFAULT '',
    tex_path     TEXT NOT NULL DEFAULT '',
    width        INTEGER DEFAULT 0,
    height       INTEGER DEFAULT 0,
    updated_at   TEXT DEFAULT (datetime('now','localtime')),
    PRIMARY KEY(version_code, camo_name, texture_tag)
);
