# 全库代码重复与低效优化计划

- 日期:2026-08-21(基于当前仓库代码彻底重写)
- 范围:**全库**(services/ models/ data_extractor/ utils/ ui/ app/ presenters/ uncode_assets/ 根文件)
- 已排除:`_archive/`(归档老代码)、`scripts/`(独立脚本)、`data/`、`docs/`、`resources/`
- 用户范围决定:
  - data_extractor 只做低风险项(删死代码/合并同函数/去冗余分配,**不动解码算法**)
  - geometry 新代码内部重复仅标注,本轮不处理
  - 仓库无 pytest;验证靠 selftest 脚本 + 等价性断言 + GUI 冒烟

---

## 〇、自上次审计以来的代码变更(2026-08-19 → 08-21)

| 变更 | 影响 |
|---|---|
| `assets_cache_service.py` 从 612→**941 行** | 新增 `get_skeleton_bones_decoded`/`get_shape_names`/`_murmur3_32`/`_decompose_mat`/`_quat_to_mat` 等;populate 增写 skeleton_bones/shape_names/material_full 表 |
| `geometry_service.py` `AssetsCacheService()` 实例化 6→**9 处** | AC11 恶化 |
| `analysis_service` 移除 `_get_assets_svc`/`_ship_mount_map` | **旧 A3/A4 已解决**(挂点数据改由 assets_data.db 提供) |
| `ship_presenter`/`firing_arc_dialog` 新增 `get_skeleton_mounts` 调用 | assets_cache_service 使用面扩大 |
| `processor_service._populate_assets_cache`(L334) | 依赖 `GeometryService._locate_assets_bin` 私有方法(AC14) |
| **新重复**:`_murmur3_32` 在 `assets_cache_service`(L248) 与 `geometry_service`(L1217) 逐字重复 | AC15 |

---

## 一、审查发现汇总(全部经当前代码逐项验证)

### 1.1 services/ + models/ 层

| ID | 位置 | 问题 | 级别 |
|---|---|---|---|
| B1 | `processor_service.py` L221 `struct.pack('B'*N, *gpd[::-1])` | 数百 MB 展开成参数:内存翻倍+极慢+崩溃风险;= `gpd[::-1]` | 高 |
| A1 | `ballistics_service.py` `calc_ap_penetration`(L125) vs `calc_v3_penetration`(L129) | **数学等价**穿深公式 | 高 |
| A6 | `analysis_service.py` precompute_all L1726-1745 vs L1784-1803 | PCOK/PCOL/雷场处理块**逐字重复** | 高 |
| A2 | `database_service.import_po_translations`(L989) vs `localization_service._join_po_multiline`(L91) | PO 多行 msgstr 合并逻辑重复 | 中 |
| A5 | `extractor_service._get_latest_bin`(L27) / `extractor._find_latest_bin`(L179) / `localization_service`(L210-218) | "找最新 bin 目录" 3 份 | 中 |
| B2 | `localization_service.py` L61 | 逐个舰长对整份 PO 跑 regex O(crew×po) | 中 |
| B3 | `skill_service.py` L194 | `_icon_to_skill_key` 每次全表 `SELECT DISTINCT skill_key` | 中 |
| B5 | `diff_service.py` `build_overview`(L369) | 快照已载入内存(`_load_snapshot_map` L130)又逐实体 `_get_snapshot`(L210) 重查 | 中 |
| B8 | `analysis_service.store_ship` 系列 | 每艘船对同一 raw_data 多次全量扫描(见 N7/N8) | 中 |
| A12 | `database_service.initialize`(L149-499) | ~19 个同构 `PRAGMA table_info` + ALTER 样板块 | 中 |
| N15 | `database_service.py` L748/768/789/811/827/844/872/890/907 | "空 vc → 取最新版本"回退样板**重复 9 次** | 中 |
| N16 | `database_service.py` ~15 处 | `except sqlite3.OperationalError: return ...` 样板重复 | 中 |
| N17 | `database_service.get_stats`(L906) | 对 ENTITY_TYPES 逐类 COUNT(*) = **N+1 计数** | 中 |
| N5 | `analysis_service._write_upgrade_info`(L657,L698) | 每 module id 单独 `SELECT 1 FROM name_mappings` | 中 |
| N6 | `analysis_service._write_depth_charge`(L1110,L1130) | 每炮按 ammo_id 单独查 | 中 |
| N7 | `analysis_service._write_engine`(L806) | 同一份 raw_data **全量扫 3 次**(收集 keys/查 Hull 速度/兜底) | 中 |
| N13 | `analysis_service._write_aa`(L1080,L1098) | 循环内 `next(i for i in items if ...)` **O(n²)** | 中 |
| N1 | `analysis_service` PROJECTILE_EXT_MAP(L134) `Mine`(L213) vs `PlaneSeaMine`(L227) | 逐字重复条目 | 中 |
| N2 | 同上 `Bomb`(L177) vs `SkipBomb`(L195) | 21 列配置只差最后一个 lambda | 中 |
| N18 | `name_mapping.py` `MODIFIER_MAP`(L9) vs `MODIFIER_FORMAT_MAP`(L276) | 键集 ~100% 重复,需手工同步 | 高 |
| N19 | `name_mapping.py` `RIBBON_MAP`(L674) vs `RIBBON_MAP_CREW`(L684) | 键完全相同,仅 `"13"` 一个值不同 | 中 |
| N20 | `name_mapping.py` `get_modifier_color`(L579) vs `format_modifier`(L600) | 前段归一化逻辑重复 | 中 |
| A7 | `database_service._entity_type`(L678) / `get_categories` / `ENTITY_TYPES` | 实体类型映射多处 | 低 |
| A13 | `database_service._drop_all_tables` vs `drop_all` | 表遍历重复 | 低 |
| A14 | `ballistics_service.interpolate_at_distance`(L150) vs 内联插值 vs `ui/penetration_calculator` | 线性插值 3 份 | 低 |
| A15 | `ballistics_service.generate_full_table`(L387) | 无调用者(UI 内联重复) | 低 |
| A16 | `models/analysis_result.py` `DataItem.__lt__` vs `sorted_items` | 排序双实现 | 低 |
| B6 | `generate_full_table` 循环内 | 重复取恒定常量 | 低 |
| B7 | `database_service.initialize` | ~19 次独立 commit | 低 |
| B9 | ballistics 插值 | while 线性查找可换 bisect | 低 |
| N3 | `analysis_service` store_ship 武器 HP 循环 | Artillery/SecondaryArtillery 两块逐字相同 | 中 |
| N4 | `analysis_service` `_write_artillery`(L901)/`_write_atba`(L933)/`_write_secondary_artillery`(L954) | ~90% 结构相同 | 中 |
| N8 | `analysis_service` L338 | `has_pure_b_air` 在外层循环内计算 | 中 |
| N9 | `analysis_service` L1662 | `startswith("PCOK") or startswith("PCOK_")` 冗余 | 低 |
| N10 | `analysis_service` L1262 | SkipBomb 死分支 | 低 |
| N11 | `analysis_service` L13-18 | 未使用 import(sqlite3/defaultdict/Callable/Optional/Path) | 低 |
| N12 | `analysis_service` store_plane | `_v` 冗余 isinstance 判断 | 低 |
| N14 | `analysis_service` precompute_all 磁盘分支 | `len(list(glob))` 物化列表仅计数 | 低 |
| N21 | `name_mapping.py` | 颜色方向注释块复制错位 | 低 |
| N22 | `name_mapping.py` `BUOYANCY_MAP`(L252) vs `DEPTH_MAP`(L694) | 部分重叠易混淆 | 低 |

### 1.2 data_extractor/ 层

| ID | 位置 | 问题 | 级别 |
|---|---|---|---|
| D1⚠ | `kraken.py` `decompress`(L3104) vs `decompress_stream`(L3188) | ~90% 相同解压状态机(本轮不做) | - |
| D2 | `kraken.py` `_bswap32`(L636) vs `_byteswap`(L836) | 同 32 位字节交换 | 中 |
| D3 | `kraken.py` `_u32le/_u16le` vs `_le4` | LE 读 helper 重叠 | 低 |
| D4 | `kraken.py` `CODE_PREFIX_ORG` 定义 3 次(L409/545/759) | 提升模块级常量 | 中 |
| D5 | `extractor.py` `list_files`(L217)/`_match_files`(L399)/`_match_pattern`(L195) | 三份全树 fnmatch(第 3 份死代码) | 中 |
| D6⚠ | `pkg_reader.py` `read_file`(L122) vs `extract_to_file`(L194) | 模式分派重复(可选) | - |
| D7 | `pkg_reader.py` `file_needs_bc7prep`(L265) vs `_decode_bc7prep`(L291) | DDS 头检测重复 | 中 |
| D8 | `idx_parser.py` v20 名字解析 | 未复用 `_read_null_terminated_string`(L99) | 低 |
| P1 | `extractor.py` `list_files`/`_match_files` | 每次全树 O(patterns×N) fnmatch | 中 |
| P2 | `pkg_reader.parse_container_header`(L91) | 白算 O(块数) 描述符 | 中 |
| P3 | `pkg_reader.decode_bc7prep_file`(L278) | 每纹理 2 次 IO | 低 |
| P4 | `kraken._decode_golomb_rice_lengths` | 热循环每符号建 list | 中 |
| P5 | `kraken.BitReader2.read_bits` | 逐 bit 调用(谨慎) | 中 |
| P6 | `kraken._decode_rle`(L974) | 固定 ≥1MB 缓冲 | 低 |
| P7 | `kraken.decompress` | 未用 scratch 参数 | 低 |
| N23 | `data_extractor/cli.py` 6 个 cmd_*(L54/63/80/101/131/145) | `GameExtractor(...)` + close 样板重复 | 低 |
| N24 | cli `cmd_list` vs `cmd_search` | 打印块逐字重复 | 低 |
| N25 | cli L47-48 | 未使用 import `list_files_fn`/`extract_files_fn` | 低 |

### 1.3 ui/ 层

| ID | 位置 | 问题 | 级别 |
|---|---|---|---|
| U1 | `detail_panel.py`×2 + `crew_customize_dialog.py`(L143/L211) | 天赋/技能触发格式化 **3 处重复** | 高 |
| U2 | `penetration_calculator.py` | 主线程全量重算+重建 4 张图;滑条每格重算 3000 发散点(L2357) | 高 |
| U3 | `penetration_calculator._mod_matches`(L1760) vs `ship_presenter._build_config_bar`(L3016) | 升级品匹配**显式复制** | 高 |
| U4 | 懒创建单实例+居中样板 **5+ 处** | main_window/toolbar_widget/detail_panel/firing_arc_dialog(L698)/gui(L169) | 高 |
| U5 | `detail_panel.py` `_proj_to_air` L2394/2586/2842 | 弹药图标候选解析 3 处重复 | 中 |
| U6 | 名称解析裸 SQL 5+ 处 | penetration_calculator(L803)/firing_arc_dialog(L516,535)/crew_customize_dialog(L594)/detail_panel | 中 |
| U7 | 舰船列表加载 3 套 | browser_panel/penetration_calculator/geometry_viewer | 中 |
| U8 | `detail_panel.resizeEvent`(L161) | 每次缩放全量重建舰船网格 | 中 |
| U9 | `penetration_calculator.py` L179 | 重定义 `NATION_MAP`(Mapping 已有) | 中 |
| U10 | `penetration_calculator.py` 图表样板 | `_build_curve_chart`(L1944) 等 4 处重复 | 低 |
| U11 | `version_diff_dialog._DiffSignals` | run_async 回调已在主线程,Signal 冗余 | 低 |
| U12 | `ship_card_widget.SECTION_ICONS` vs `module_select.SHIP_MODULE_MAP` | 两套平行图标表 | 低 |
| U13 | `detail_panel._additive_keys` L1523/3475/3538 | 相同集合重复 3 次 | 低 |
| U14 | 按钮 QSS / combo 箭头 QSS | 多处复制 | 低 |

### 1.4 app/ + presenters/ + main.py 层

| ID | 位置 | 问题 | 级别 |
|---|---|---|---|
| AP1 | `detail_panel._on_consumable_btn_click`(L3891) vs `ship_presenter._append_consumables`(L606) | 消耗品渲染**整段重写** | 高 |
| AP2 | `ship_presenter._build_ap_pen_summary`(L578) | 每 AP 弹种整条弹道积分无缓存(L594) | 高 |
| AP3 | 名称解析/版本查询 3+ 份 | base_presenter(L36/48/92)/database_service/detail_panel/penetration_calculator | 高 |
| AP11 | `base_presenter.py` | resolve_name 无缓存,单次 build 上百条 SQL | 高 |
| AP4 | `ship_presenter.MODIFIER_MAP`(L24) vs `Mapping.MODIFIER_MAP`(L9) | 两套字典需手工同步 | 中 |
| AP5 | 技能/天赋渲染 3 处 | crew_customize_dialog/detail_panel/penetration_calculator 各自内联 SQL | 中 |
| AP6 | `ship_presenter` 弹药详情构建 | 多炮种分支重复查询+格式化 | 中 |
| AP8 | `application.set_theme_mode`(L133) + `theme.refresh`(L143) + main.py(L182) | 主题刷新双触发 | 中 |
| AP9 | `ship_presenter` N+1 | 弹种循环逐条查;_append_modules 每 letter 重复查 | 中 |
| AP7 | `app/config.py`/`application.py` | 配置属性样板 15+ 处 | 低 |
| AP10 | `main.py` `load_stylesheet`(L93) 死包装;`folder_selected` 双发射(L214/220) | 杂项 | 低 |
| AP12 | `tools/` 两 exe + `path_utils.get_tools_dir` | 废弃死代码 | 低 |

### 1.5 uncode_assets/ 层

| ID | 位置 | 问题 | 级别 |
|---|---|---|---|
| UA1 | `decoders.py` `build_self_id_index()` L28/196/309 | 每次调用重建全表索引,**无缓存**(parser.py L222 每次 new dict)→ O(N²) | 高 |
| UA2 | `parser.get_prototype_data`(L183) | `db.data[offset:]` 整段复制;dump/decode_path_json 未用有界切片 | 高 |
| UA3 | `parser.py` L377 `blob = data[...]` | bytes 切片恒复制,峰值内存 ≈2× 文件 | 中 |
| UA4 | `parser.get_string_by_id`(L66) | 开放寻址线性探测无缓存 | 中 |
| UA5 | 字节 helper 3 类重复 | binary(L103/72/84) ≡ idx_parser(L99) ≡ geometry_parser(L262/266) | 中 |
| UA6 | `service.load_from_game`(L73) vs `extractor_service._extract_assets_bin`(L87) | assets.bin 提取流程重复 | 中 |
| UA7 | `decoders._particle_refs`(L68) | 无收集上限 | 低 |
| N26 | `uncode_assets/cli.py` 8+ 个 cmd_* | `_make_service` + close 样板重复 | 低 |
| N27 | cli except 样板 4 处 | `except AssetsBinError: print; exit` | 低 |
| N28 | cli L33 `import json` 未使用;L156 用 `__import__("json")` | 风格不一致 | 低 |
| N29 | `gui.py` except 元组冗余 | `(AssetsBinError, KeyError, ValueError, Exception)` | 低 |
| N30 | `gui.py` `_find_dir_item`(L269) vs `_reveal_file`(L339) | 路径查找循环重复 | 低 |
| N31 | `gui.py` `_on_search`(L312) | all_files() 迭代两遍 | 低 |
| N32 | `gui.py` L24 | 未使用 import QFont | 低 |

### 1.6 assets_cache_service.py 专属发现(941 行)

| ID | 位置 | 问题 | 级别 |
|---|---|---|---|
| AC1 | `populate()` 材质解析(L514-600) ≈ `decoders.decode_material` | mfm 格式布局知识双份维护 | 高 |
| AC2 | `populate()` 渲染集扫描(L423-490) ≈ `decoders._visual_render_sets` | 渲染集/damage 判定双份 | 高 |
| AC4 | `_strings_dict`(L899) vs `GeometryService._strings_dict`(L1708) | **逐字一致** | 中 |
| AC5 | `_material_family`(L765) vs `GeometryService._material_family`(L1857) | **逐字一致** | 中 |
| AC6 | `_to_render_row`(L933) vs `GeometryService._matrix_to_render`(L1020) | 同逻辑(列→行主序) | 低 |
| AC7 | `_init_core_tables_inline`(L129) vs `assets_database.sql` | schema 双份 | 中 |
| AC10 | `has_data()`(L612) | **全库无调用**(死代码) | 低 |
| AC10b | meta 表 `game_version/wows_type/created_at`(L134-136) | 只写不读 | 低 |
| AC11 | `geometry_service.py` **9 处** `AssetsCacheService()`(L861/1046/1068/1207/1490/1761/1816/1889/1930) | 每次 new 实例→新 sqlite 连接 | 高 |
| AC12 | assets.bin 定位 3 套 | geometry `_locate_assets_bin`(L960)/service `load_from_game`(L73)/extractor_service(L87) | 高 |
| AC13 | 懒加载 AssetsBinService 2 份 | geometry `_get_assets_service`(L1004) + populate 内直接构造 | 中 |
| AC14 | `processor_service._populate_assets_cache`(L343) | 依赖 geometry **私有方法** `_locate_assets_bin` | 中 |
| AC15 | `_murmur3_32` `assets_cache_service`(L248) vs `geometry_service`(L1217) | **逐字重复**(新发现) | 中 |
| AC3 | populate 骨架遍历全量 vs analysis 已验证 `*_ports` 过滤省 60% | populate 未复用该优化 | 中 |
| AC8 | 函数内 `import numpy as np`(多处) | 重复 import(风格) | 低 |
| AC9 | `_conn` 首连/重连块 | 重连漏 `synchronous=NORMAL` | 低 |

### 1.7 其他次要

| ID | 位置 | 问题 | 级别 |
|---|---|---|---|
| N34 | `utils/qrc_rebuilder.py` L28 `_EXCLUDE` vs `scripts/gen_qrc.py` | 常量双份硬编码 | 低 |
| N35 | `utils/theme.py` `qss()`(L175) | 每 key 一次 `.replace`(~30 次全量扫描) | 中 |
| N36 | `models/dds_reader.py` L149 | mip 循环内重算常数 block_bytes | 低 |

### 1.8 死代码汇总

| 位置 | 说明 |
|---|---|
| `uncode_assets/shaders.py`(359 行,整模块) | 全库零引用 → 移入 `_archive/` |
| `uncode_assets/binary.py` 4 死函数 | `resolve_relptr_at`(64)/`parse_i32_array`(127)/`parse_f32_array`(134)/`parse_bounding_box`(171) |
| `uncode_assets/types.py` 3 死函数 | `type_from_extension`(96)/`can_decode_name`(119)/`default_item_sizes`(142) |
| `uncode_assets/decoders.py` `decode_record`(689) | 仅再导出;`service.py:25` 死 import |
| `uncode_assets/vfs.py` `files_with_type`(342)、`service.py` `can_decode_path`(285) | 无调用 |
| `data_extractor/kraken.py` | `_lookup`(600)/`_huff_convert_to_ranges`(366)/`_parse_quantum_header` 不可达块(862+)/反向流分支 |
| `data_extractor/pkg_reader.py` `_load_pkg`(70)+`clear_cache`(315) | 从未调用 |
| `data_extractor/extractor.py` `_match_pattern`(195)/`flatten`(276/529) | 死代码/未使用 |
| `ballistics_service.generate_full_table`(387) | 无调用者 |
| `tools/` 两 exe + `path_utils.get_tools_dir` | 废弃 |
| `main.py load_stylesheet`(93) | 死包装 |
| `assets_cache_service.has_data`(612) | 无调用 |
| `analysis_service` 未使用 import(L13-18) | sqlite3/defaultdict/Callable/Optional/Path |
| `data_extractor/cli.py` L47-48 | 未使用 import |
| `uncode_assets/cli.py` L33 | 未使用 import json |
| `uncode_assets/gui.py` L24 | 未使用 import QFont |

### 1.9 已解决项(本次确认不再存在)

| 旧 ID | 说明 |
|---|---|
| A3 | `analysis_service._get_assets_svc` 已移除(挂点改由 assets_data.db 提供) |
| A4 | `analysis_service._ship_mount_map` 已移除 |

---

## 二、实施阶段(按风险/收益排序)

### Phase 0:快赢(低风险高收益) ✅ 已完成(2026-08-21)

1. **B1** 字节反转:`processor_service.py` L221 改 `gpd = gpd[::-1]`。✅(5 组随机等价断言通过)
2. **A1** 穿深公式合并:`calc_ap_penetration` 改调 `calc_v3_penetration`。✅(20 组随机等价断言通过)
3. **A6** `precompute_all` 抽 `_store_skills_and_minefields()`。✅(内存/磁盘两分支共用)
4. **UA1** `build_self_id_index()` 加惰性缓存(parser.py @property)。✅(合成数据验证缓存命中)
5. **UA4** `StringsSection` 预计算 `dict[int, str]`。✅(合成数据验证 O(1) 查找)
6. **AC10** 删 `has_data` + meta 只写列。✅(has_data 已删;meta 只写列保留——删列属 schema 变更,超出本轮边界)
7. **N11/N25/N28/N32** 删未使用 import(4 文件)。✅(analysis_service 另删 os/math/defaultdict/Callable/Optional/Path)
8. **N9/N10** 删冗余条件/死分支。✅

### Phase 1:data_extractor 低风险清理(不动算法)

1. 死代码删除(kraken/pkg_reader/extractor 如 1.8 所列)。
2. 同函数合并:D2/D4/D7。
3. 去冗余:P6/P7。
4. *(可选)* P2/P3/P4。

### Phase 2:services 层收敛

1. **A2+B2**:抽 `utils/po_utils.py`;舰长名改查表。
2. **A5**:抽 `find_latest_bin_folder()`。
3. **B3** skill_service 缓存 skill_key。
4. **B5** diff_service 快照内存复用。
5. **A12+B7+N15+N16** 迁移 helper + `_resolve_vc()` + `_safe_query`。
6. **N17** get_stats 改 GROUP BY。
7. **N5/N6/N7/N13** analysis 写入 N+1 与重复扫描修复。
8. **N1/N2/N3/N4** PROJECTILE_EXT_MAP 与 writer 收敛。
9. **N18/N19/N20** name_mapping 派生/合并。
10. **A15+B6** generate_full_table 处置。
11. **A7/A13/A14/A16/B9** 小项收敛。

### Phase 3:uncode_assets + assets_cache 性能与去重

1. **UA2** 有界切片通用化。
2. **UA3** memoryview 替代 bytes 切片。
3. **UA5** 字节 helper 统一。
4. **UA6+AC12** assets.bin 定位/提取统一为单一 helper。
5. **AC11** geometry_service 9 处实例化 → 单实例持有。
6. **AC13+AC14** 懒加载统一;processor 解除私有耦合。
7. **AC4/AC5/AC6/AC15** 逐字重复提取共享(`_strings_dict`/`_material_family`/矩阵转换/`_murmur3_32`)。
8. **AC1/AC2** 格式知识双份 → 提取共享 fast-path(可后续)。
9. **AC7** schema 单一来源。
10. 死代码清理(shaders.py → _archive;binary/types/decoders/vfs/service 死函数)。

### Phase 4:UI 层收敛

1. **U1** 抽 `crew_skill_formatter`。
2. **U6+AP3+AP11** 名称解析收敛 + 缓存。
3. **AP1** 消耗品渲染去重。
4. **U3** 升级品匹配共享。
5. **U4** 抽 `window_utils`。
6. **AP2** 弹道 LRU 缓存。
7. **U2+U8+U10** 穿深计算器防抖+缓存;detail_panel resize 防抖。
8. **AP4/AP5/U5/U9/U12/U13/U14** 常量/渲染统一。

### Phase 5:app/ + main.py + 杂项

1. **AP7** 配置样板收敛。
2. **AP8** 主题刷新去重。
3. **AP10** 死包装+双发射。
4. **AP9** ship_presenter N+1 批量化。
5. **AP12** tools/ 清理。
6. **N23-N27** cli 样板收敛。
7. **N34/N35/N36** 杂项。

---

## 三、验证(每阶段)

- **B1**:`struct.pack('B'*len, *gpd[::-1]) == gpd[::-1]` 等价断言。
- **A1**:随机参数两公式结果一致(容差 1e-9)。
- **UA1/UA4**:同一 assets.bin dump 结果逐字节一致;性能对比。
- **data_extractor**:提取单文件前后输出字节一致。
- **services**:`_archive/scripts/selftest_service.py` 回归;DB 导入条数断言。
- **UI**:`python main.py` GUI 冒烟。
- 每阶段 `get_errors` 确认无语法错误。

---

## 四、范围边界

- 不处理:geometry 新代码内部重复仅标注;
- 不做:D1 双状态机合并(用户否决);D6 可选;
- 死代码建议**移入 `_archive/`** 而非删除;
- 不引入新依赖、不改 DB schema、不改格式解析语义。
