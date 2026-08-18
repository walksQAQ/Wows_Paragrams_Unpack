# 全库代码重复与低效优化计划

- 日期:2026-08-18
- 范围:**全库**(services/ models/ data_extractor/ utils/ ui/ app/ presenters/ uncode_assets/ 根文件)
- 已排除:`_archive/`(未使用归档老代码)、`scripts/`(独立脚本)、`data/`(数据)、`docs/`(文档)、`resources/`(资源)
- 用户范围决定:
  - 交付 = 审查报告 + 分阶段优化计划(批准后实施)
  - data_extractor 只做低风险项(删死代码/合并同函数/去冗余分配,**不动解码算法**)
  - geometry 跨模块重复仅标注,本轮不处理
  - 仓库无 pytest;验证靠 selftest 脚本 + 等价性断言 + GUI 冒烟

---

## 一、审查发现汇总

### 1.1 services/ + models/ 层

| ID | 位置 | 问题 | 级别 |
|---|---|---|---|
| A1 | `ballistics_service.py` `calc_ap_penetration`(L125) vs `calc_v3_penetration`(L129) | **数学等价**穿深公式 | 高 |
| A2 | `database_service.import_po_translations`(L918-957) vs `localization_service._join_po_multiline`(L90-117) | PO 多行 msgstr 合并逻辑逐行相同 | 中 |
| A3⚠ | `analysis_service._get_assets_svc`(L294) vs `geometry_service._get_assets_service`(L617) | assets.bin 懒加载(仅标注) | - |
| A4⚠ | `analysis_service._ship_mount_map`(L359-381) vs `geometry_service._load_mount_transforms`(L663-710) | 骨架挂点解码+缓存(仅标注) | - |
| A5 | `extractor_service._get_latest_bin`(L27) / `extractor._find_latest_bin`(L179) / `localization_service`(L210-218) | "找最新 bin 目录" 3 份 | 中 |
| A6 | `analysis_service.precompute_all` L1886-1916 vs L1944-1974 | PCOK/PCOL/雷场处理块**逐字重复** | 高 |
| A7 | `database_service._entity_type`(L665) / `get_categories` rev(L818) / `ENTITY_TYPES`(L16) | 实体类型正/反向映射 3 处 | 低 |
| A12 | `database_service.initialize`(L141-540) | ~20 个同构 ALTER TABLE 样板块,独立 commit | 中 |
| A13 | `database_service._drop_all_tables`(L92) vs `drop_all`(L1065) | 表遍历重复 | 低 |
| A14 | `ballistics_service.interpolate_at_distance`(L150) vs `calculate_full_ballistics` 内联(L268) vs `ui/penetration_calculator`(L1906) | 线性插值 3 份 | 低 |
| A15 | `ballistics_service.generate_full_table`(L387) | 疑似死代码(无调用者,UI 内联重复) | 低 |
| A16 | `models/analysis_result.py` `DataItem.__lt__`(L23) vs `sorted_items`(L33) | 排序双实现 | 低 |
| B1 | `processor_service.py` L114 `struct.pack('B'*N, *gpd[::-1])` | 数百 MB 展开成参数:内存翻倍+极慢+崩溃风险;= `gpd[::-1]` | 高 |
| B2 | `localization_service.py` L60-72 | 逐个舰长对整份 PO 跑 regex O(crew×po) | 中 |
| B3 | `skill_service.get_grid_skills`(L207) | 每格 ~96 次 DB 查询,`_icon_to_skill_key` 每次全表 SELECT | 中 |
| B5 | `diff_service.build_overview`(L369) | 快照已载入内存又 2 次 SQL 重读 | 中 |
| B6 | `generate_full_table`(L406-424) | 循环内重复取恒定常量 | 低 |
| B7 | `database_service.initialize` | ~20 次独立 commit | 低 |
| B8 | `analysis_service.store_ship`(L462/495/882/948/975) | 每艘船对同一大 dict 4+ 次全量扫描 | 中 |
| B9 | ballistics 插值 while 线性查找 | 换 bisect | 低 |

### 1.2 data_extractor/ + utils/ 层

| ID | 位置 | 问题 | 级别 |
|---|---|---|---|
| D1⚠ | `kraken.py` `decompress`(L3104) vs `decompress_stream`(L3188) | ~90% 相同解压状态机(本轮不做) | - |
| D2 | `kraken.py` `_bswap32`(L636) vs `_byteswap`(L836) | 同 32 位字节交换 | 中 |
| D3 | `kraken.py` `_u32le/_u16le`(L628/632) vs `_le4`(L1425) | LE 读 helper 重叠 | 低 |
| D4 | `kraken.py` `CODE_PREFIX_ORG` 定义 3 次(L545/L759/L409 参数默认) | 提升模块级常量 | 中 |
| D5 | `extractor.py` `list_files`(L217)/`_match_files`(L399)/`_match_pattern`(L195) | 三份全树 fnmatch(第 3 份死代码) | 中 |
| D6⚠ | `pkg_reader.py` `read_file`(L122) vs `extract_to_file`(L194) | 模式分派重复(合并需重构,可选) | - |
| D7 | `pkg_reader.py` `file_needs_bc7prep`(L265) vs `_decode_bc7prep`(L291) | DDS+0x7BC 头检测重复 | 中 |
| D8 | `idx_parser.py` v20 名字解析(3 处)未复用 `_read_null_terminated_string`(L99) | 名字解析 helper 未复用 | 低 |
| P1 | `extractor.py` `list_files`/`_match_files` | 每次全树 O(patterns×N) fnmatch | 中 |
| P2 | `pkg_reader.parse_container_header`(L91-118) | 白算 O(块数) 描述符(调用方只读 2 字段) | 中 |
| P3 | `pkg_reader.decode_bc7prep_file`(L278-287) | 每纹理 2 次 IO | 低 |
| P4 | `kraken._decode_golomb_rice_lengths`(L281) | 热循环每符号建 8 元素 list | 中 |
| P5 | `kraken.BitReader2.read_bits`(L265) | 逐 bit 调用(动热路径,谨慎) | 中 |
| P6 | `kraken._decode_rle`(L974) | 固定 ≥1MB 缓冲 | 低 |
| P7 | `kraken.decompress` | 每 256KB 块空分配未用 scratch | 低 |

### 1.3 ui/ 层(新增)

| ID | 位置 | 问题 | 级别 |
|---|---|---|---|
| U1 | `detail_panel.py`(1277-1520 / 1770-1900)×2 + `crew_customize_dialog.py`(137-250) | 舰长天赋/技能触发格式化逻辑 **3 处重复**(trigger/effects/modifier→tooltip) | 高 |
| U2 | `penetration_calculator.py` | 主线程全量重算 + 每次选中重建 4 张 matplotlib 图;滑条每动一格重算最多 3000 发高斯散点 | 高 |
| U3 | `penetration_calculator._mod_matches`(1760-1790) vs `ship_presenter._build_config_bar`(3041-3068) | 升级品可用性匹配**显式复制**(docstring 自认"完全一致") | 高 |
| U4 | 懒创建单实例+居中+几何保存样板 **5 处** | `main_window.py`(150/164) / `toolbar_widget.py`(197/211) / `detail_panel.py`(2265);`center_on_screen` 4 份、`_save/_restore_geometry` 2 份 | 高 |
| U5 | `detail_panel.py` 弹药图标候选解析 **4 处**(约 2330/2630/2770/3170) | `_proj_to_air`+鱼雷回退+深弹回退重复 | 中 |
| U6 | 名称解析裸 SQL 6 处 | `penetration_calculator`(803)/`firing_arc_dialog`(516)/`detail_panel`(1584)/`crew_customize_dialog`(594)/`penetration_calculator`(1670,1723) 各自内联,绕过 `BasePresenter.resolve_name` | 中 |
| U7 | 舰船列表加载 3 套 | `browser_panel`(262)/`penetration_calculator`(819)/`geometry_viewer`(294) 各自拼 SQL | 中 |
| U8 | `detail_panel.resizeEvent`(161) | 每次缩放全量重建舰船网格(几十张卡片×QTableWidget);点升级品/技能/信号旗也全量重建 | 中 |
| U9 | `penetration_calculator.py`(179-203) | 重新定义 `NATION_MAP`/`SHIP_CLASS_MAP`(`Mapping` 已有集中版) | 中 |
| U10 | `penetration_calculator.py` 图表样板重复 4 次 | `_build_curve_chart`(1944)/`_build_flytime_chart`(2012)/`_build_metric_chart`(2070)/`_build_dispersion_ellipse`(2295) | 低 |
| U11 | `version_diff_dialog._DiffSignals`(43-48) | `run_async` 回调本就在主线程,Signal 二次转发冗余 | 低 |
| U12 | `ship_card_widget.SECTION_ICONS`(90-103) vs `module_select.SHIP_MODULE_MAP`(21-47) | 两套平行图标表 | 低 |
| U13 | `detail_panel._additive_keys` 重复 3 次(约 1500/3420/3510) | 相同修饰符键集合 | 低 |
| U14 | 按钮 QSS / combo 箭头 QSS 多处复制 | `detail_panel` 5 份 BTN_STYLE + `penetration_calculator`(250-270)/`detail_panel`(1000-1060) | 低 |

### 1.4 app/ + presenters/ + main.py 层(新增)

| ID | 位置 | 问题 | 级别 |
|---|---|---|---|
| AP1 | `detail_panel._on_consumable_btn_click`(3855-4172) vs `ship_presenter._append_consumables`(540-760) | 消耗品渲染**整段重写**(查表→extra_json→类型分支渲染),最严重跨层重复 | 高 |
| AP2 | `ship_presenter._build_ap_pen_summary`(505-530) | 每个 AP 弹种整条弹道积分,无 memoization;同弹种主/副炮重复算 | 高 |
| AP3 | 名称解析/版本查询 3+ 份 | `base_presenter`(41/59/97)/`database_service`(645/916)/`detail_panel`(3872)/`penetration_calculator`(803) | 高 |
| AP4 | `ship_presenter.MODIFIER_MAP`(26-137) vs `Mapping.MODIFIER_MAP`(14-220) | 同批 modifier key 两套字典(长描述 vs 短标签),key 需手工同步 | 中 |
| AP5 | 技能/天赋渲染 3 处 | `crew_customize_dialog`(109)/`detail_panel`(1076)/`penetration_calculator`(1625) 各自内联 SQL,未统一走 `SkillService` | 中 |
| AP6 | `ship_presenter` 弹药详情构建复制 3+ 次 | `_build_artillery`(1294)/`_build_atba`(1685)/`_build_secondary_artillery`(1736)/`_build_aircraft_panel` 各分支重复 `projectile_bullet_ext` 查询+`_append_ammo_*` | 中 |
| AP7 | 配置读写代理样板 15+ 处 | `app/config.py`(31-92) 7 对 property + `app/application.py`(65-101) 8 个 setter 手写 | 低 |
| AP8 | 主题刷新双触发 | `application.set_theme_mode`(91-99)+`main.py._on_theme_changed`(186-200) 各 `theme.refresh()` 一遍 + 各 widget 监听再全量 restyle | 中 |
| AP9 | N+1 查询模式 | `ship_presenter` 弹种循环逐条查 `projectile_basic_info`/`projectile_bullet_ext`;`_append_modules` 每 letter 重复查 `ship_basic_info`/`entity_registry` | 中 |
| AP10 | `main.py` 杂项 | `load_stylesheet`(114-121) 死包装;`_auto_refresh`(206-231) 与 `main_window.__init__`(157) 双发射 `folder_selected("Ship")` | 低 |
| AP11 | `presenters/base_presenter.py` 无缓存 | `resolve_name` 单次 build 30+ 调用点各发一条 SQL;`get_name_map("ammo")` 单次 build 6 次整表查 | 高 |
| AP12 | `tools/` 两 exe + `path_utils.get_tools_dir`(73) | 已改用纯 Python `data_extractor`,属废弃死代码 | 低 |

### 1.5 uncode_assets/ 层(新增)

| ID | 位置 | 问题 | 级别 |
|---|---|---|---|
| UA1 | `decoders.py` `_resolve_path_id`(24-32) 每次调用重建 `build_self_id_index()` | 解码热路径 **O(N²)**:`decode_material` 每个 texture 属性一次全表 O(P) 索引重建(P≈10万) | 高 |
| UA2 | `parser.py` `get_prototype_data`(183-194) `db.data[offset:]` | bytes 切片=整段复制,73MB Skeleton 每条记录拷全尾部;`dump`/`decode_path_json`/GUI 路径未受益 | 高 |
| UA3 | `parser.py` 解析期 bytes 切片复制(326/377/424) | `bytes[a:b]` 恒复制,峰值内存 ≈2× 文件(≈500MB),与模块注释"视图切片"矛盾 | 中 |
| UA4 | `parser.StringsSection.get_string_by_id`(66-94) 无缓存 | 解码热路径反复开放寻址探测(渲染集/属性名/粒子引用) | 中 |
| UA5 | 字节 helper 3 类重复 | `read_null_terminated_string`(binary:103 ≡ idx_parser:99);`parse_packed_string`(binary:72 ≡ geometry_parser:266 ≡ parser:245 内联);`resolve_relptr`(binary:60 ≡ geometry_parser:260) | 中 |
| UA6 | `service.py::load_from_game`(62-85) vs `extractor_service._extract_assets_bin`(88-120) | assets.bin 提取流程重复(一处写盘一处读内存) | 中 |
| UA7 | `decoders.py:265-272` 渲染集扫描/`_particle_refs`(68-77) | 字符串哈希反查每 4 字节一次;`_particle_refs` 无收集上限 | 低 |
| UA8 | `vfs.py`/`decoders` 已有 visual 渲染集/geometry 索引 | `geometry_service._parse_visual_render_sets`(796-855) 重新实现并**再全扫一遍**(仅标注,涉及 geometry) | - |

### 1.6 死代码汇总

| 位置 | 说明 |
|---|---|
| `uncode_assets/shaders.py`(359 行,整模块) | 全库零引用,早期逆向实验遗留 → 建议移入 `_archive/` |
| `uncode_assets/binary.py` 4 死函数 | `resolve_relptr_at`(64)/`parse_i32_array`(127)/`parse_f32_array`(134)/`parse_bounding_box`(171) |
| `uncode_assets/types.py` 3 死函数 | `type_from_extension`(96)/`can_decode_name`(119)/`default_item_sizes`(142) |
| `uncode_assets/decoders.py` `decode_record`(685) | 仅 `__init__.py` 再导出;`service.py:25` 死 import |
| `uncode_assets/vfs.py` `files_with_type`(341)、`service.py` `can_decode_path`(283) | 无调用 |
| `data_extractor/kraken.py` | `_lookup`(600)/`_huff_convert_to_ranges`(366)/`_parse_quantum_header` 不可达块(890-916,执行必 NameError)/OodleBitReader 反向流分支 |
| `data_extractor/pkg_reader.py` `_load_pkg`+`_cache`+`clear_cache` | 从未调用,误用会整卷读入内存 |
| `data_extractor/extractor.py` `_match_pattern`(195,有 bug)/`flatten` 参数 | 无调用/未使用(含 cli.py L106、extract_files L551 透传) |
| `ballistics_service.generate_full_table`(387) | 无调用者(见 A15) |
| `tools/pfsunpack2.exe`+`wowsunpack.exe`+`path_utils.get_tools_dir` | 废弃死代码 |
| `main.py load_stylesheet`(114-121) | 死包装(仅转发 apply_theme) |

### 1.7 跨模块重复要点(汇总)

| 关注点 | 重复方 |
|---|---|
| PO 解析 | `database_service` ↔ `localization_service`(A2) |
| bin 目录查找 | `extractor_service` / `data_extractor` / `localization_service`(A5) |
| 名称解析/版本查询 | `base_presenter` / `database_service` / 4 个 UI 文件(AP3/U6) |
| 消耗品渲染 | `ship_presenter` ↔ `detail_panel`(AP1) |
| 升级品匹配 | `ship_presenter` ↔ `penetration_calculator`(U3) |
| 技能/天赋渲染 | 3 个 UI + `SkillService` 未充分复用(U1/AP5) |
| MODIFIER 字典 | `name_mapping` ↔ `ship_presenter`(AP4) |
| 弹道表计算 | `ship_presenter._build_ap_pen_summary` 无缓存(AP2) |
| assets.bin 加载/骨架缓存 | `analysis_service` ↔ `geometry_service`(A3/A4,仅标注) |
| 字节 helper | `uncode_assets/binary` ↔ `idx_parser` ↔ `geometry_parser`(UA5) |
| assets.bin 提取 | `uncode_assets/service` ↔ `extractor_service`(UA6) |

---

## 二、实施阶段(按风险/收益排序)

### Phase 0:快赢(低风险高收益,建议立即做)

1. **B1** 字节反转:`processor_service.py` L114 改 `gpd = gpd[::-1]`。
2. **A1** 穿深公式合并:保留 `calc_v3_penetration` 为实现,`calc_ap_penetration` 改为调用它。调用点:ballistics_service 内部 L269/L284、`ship_presenter.py:560`、`ui/penetration_calculator.py:1924`。⚠️ 浮点舍入可能有微小差异,需等价断言(容差 1e-9)。
3. **A6** `precompute_all` 抽 `_store_skills_and_minefields(store, other_dir, version_code)`,内存/磁盘两分支调用。
4. **UA1** `build_self_id_index()` 缓存到 `PrototypeDatabase`(@property 惰性缓存,行为不变),消除解码热路径 O(N²);顺带统一 4 处 `path_of` 反查。
5. **UA4** `StringsSection` 解析期预计算 `dict[int, str]` 哈希缓存,渲染集扫描/属性名反查变 O(1)。

### Phase 1:data_extractor 低风险清理(用户已批准范围,不动算法)

1. **死代码删除**:kraken `_lookup`/`_huff_convert_to_ranges`/`_parse_quantum_header` 不可达块/反向流分支;pkg_reader `_load_pkg`+`_cache`+`clear_cache`;extractor `_match_pattern`+`flatten`(连带清理 cli.py L106、extract_files L551)。
2. **同函数合并**:D2 `_bswap32`/`_byteswap` 统一;D4 `CODE_PREFIX_ORG` 提升模块级;D7 抽 `_is_bc7prep(data)`。
3. **去冗余分配**:P7 移除 `decompress`/`_decode_quantum` 未用 scratch 参数;P6 `_decode_rle` 上限按实际收紧(保底安全)。
4. *(可选,风险略高)* P4 每符号 list 直接写 dst;P2 `parse_container_header` 只解析实际使用字段;P3 探测后直接 seek+read 消除二次 IO。

### Phase 2:services 层收敛(排除 geometry)

1. **A2+A11+B2**:抽 `utils/po_utils.py`(`join_po_multiline`+一次性 PO→`{msgid:msgstr}`),`database_service` 与 `localization_service` 复用;B2 舰长名改查表 O(1);`run_localization` 避免 4 次读 global.po。
2. **A5**:抽 `utils/path_utils.find_latest_bin_folder(game_path)`,3 处调用。
3. **B3** `skill_service` 按 version 缓存 `skill_key` 表一次。
4. **B5** `diff_service.build_overview` 快照内存复用,消除重复 SQL。
5. **A12+B7** `database_service.initialize` 抽 `_ensure_columns(table, cols)` helper,去掉中间独立 commit。
6. **A15+B6** 让 `ui/penetration_calculator` 复用 `generate_full_table` 或删除;循环外取常量。
7. **A7/A13/A14/A16** 单一 `ENTITY_TYPE_MAP`、表遍历 helper、排序二选一、插值抽 `_interp`(bisect)。

### Phase 3:uncode_assets 性能与去重

1. **UA2** `dump`/`decode_path_json`/`decode_file` 通用化"有界切片"思路(仿 `decode_skeleton_path`),消灭 Skeleton 批量导出 GB 级拷贝。
2. **UA3** 解析期 bytes 切片改 `memoryview`,227MB 文件内存占用减半(与注释承诺一致)。
3. **UA5** 字节 helper 统一:`data_extractor/idx_parser.py` 改 import `binary.read_null_terminated_string`;抽共享 `binary_utils.py`(packed string/resolve_relptr)。
4. **UA6** assets.bin 提取字节公共逻辑收敛到 `AssetsBinService`,`extractor_service` 只负责写盘。
5. **UA7** `_particle_refs` 加收集上限;`find_path_by_suffix` 索引外提。
6. **死代码**:`shaders.py` 整模块移入 `_archive/`;binary.py 4 死函数、types.py 3 死函数、`decode_record`、`files_with_type`、`can_decode_path`、service 死 import 清理。

### Phase 4:UI 层收敛(中风险,需逐步验证)

1. **U1** 抽 `services/crew_skill_formatter.py`(`format_trigger_cond`/`format_effects_text`/`build_talent_tooltip`),3 处统一调用(收益最大且零风险)。
2. **U6+AP3+AP11** 名称解析收敛:`BasePresenter` 按 `(category)` 内存缓存;UI 一律调用 services 层,删 6 处内联 SQL。
3. **AP1** 消耗品渲染去重:UI 只消费 `ship_presenter` 已生成的 `raw_consumables`/`detail_items`,删 `_on_consumable_btn_click` 整段重复。
4. **U3** 升级品匹配抽共享纯函数 `services/modernization_service.matches(...)`,两处调用。
5. **U4** 抽 `utils/window_utils`(`open_singleton_dialog`/`center_on_screen`/几何保存),统一 5 处样板。
6. **AP2** `_build_ap_pen_summary` 按 `(mass,caliber,air_drag,velocity,krupp)` 加模块级 LRU 缓存。
7. **U2+U8+U10** 穿深计算器:弹道结果缓存 + 滑条防抖 + 升级品表预读 + matplotlib 样板抽 helper;`detail_panel` resize 防抖。
8. **AP4/AP5/U5/U9/U12/U13/U14** 常量与渲染统一:`MODIFIER_MAP` 派生、技能渲染走 `SkillService`、弹药图标解析抽 helper、删 `penetration_calculator` 重复 `NATION_MAP`、图标表/`_additive_keys`/QSS 收敛。

### Phase 5:app/ + main.py 收敛

1. **AP7** `app/config.py`/`application.py` 属性样板收敛(`__setattr__` 转发或统一 `_set(key,value,emit)` 通道)。
2. **AP8+4.3** 主题刷新去重:`set_theme_mode` 只保存+发信号,刷新统一由 `main.py` 槽处理。
3. **AP10** 删 `load_stylesheet` 死包装;`folder_selected("Ship")` 双发射去重(二选一)。
4. **AP9** `ship_presenter` N+1 改 `IN (...)` 批量查询;`_append_modules` 每 letter 重复查询改 build 开头查一次下传。
5. **AP12** 清理 `tools/` 死 exe 引用 + `path_utils.get_tools_dir`(确认无引用后)。

---

## 三、验证(每阶段)

- **B1**:修改前后 `struct.pack('B'*len, *gpd[::-1]) == gpd[::-1]` 等价断言。
- **A1**:随机参数 `calc_ap_penetration` vs `calc_v3_penetration` 结果一致(容差 1e-9)。
- **UA1/UA4**:对同一 assets.bin 样本,dump 结果与修改前逐字节一致;性能对比(ms)。
- **data_extractor**:现成数据提取单文件,修改前后输出字节一致(含 bc7prep 纹理);kraken 用已解包样本验证 `decompress`/`decompress_stream` 输出一致。
- **services**:跑 `_archive/scripts/selftest_service.py` 回归(确认未破坏共用依赖);临时脚本断言 DB 导入条数/字段一致。
- **UI**:`python main.py` GUI 冒烟(穿透计算器、本地化导入、版本比对、消耗品点击、天赋 tooltip)。
- 每阶段完成跑 `get_errors` 确认无语法/类型错误。

---

## 四、范围边界

- 不处理:geometry 新代码内部及跨模块重复(A3/A4/A8/UA8)仅标注;
- 不做:D1 `decompress`/`decompress_stream` 合并(风险最高,用户否决);D6 可选;
- `shaders.py` 等死代码建议**移入 `_archive/`** 而非直接删除(保留归档);
- 不引入新依赖、不改 DB schema、不改格式解析语义。

---

## 五、复核记录(2026-08-19)

> 复核方式:不依赖子代理报告,亲自对全部关键发现逐项 grep/read 验证。
> **结论:全部关键发现确认存在,代码主体未变(优化尚未实施)。** 用户侧仅清理了 `_archive/scripts/` 下的验证脚本(在排除范围内,不影响结论)。

### 5.1 逐项验证结果(✅ = 已亲自确认)

| ID | 验证方式 | 复核结果 |
|---|---|---|
| A1 | `ballistics_service.py` L125/L129 两公式并存 | ✅ |
| A5 | `extractor_service.py` L27 + `extractor.py` L179 + `localization_service.py` L210-218 三处并存 | ✅ |
| A6 | `analysis_service.py` precompute_all 两分支(L1886-1916 / L1944-1974)PCOK 块逐字重复 | ✅ |
| A12 | `database_service.py` `PRAGMA table_info` 样板 ~19 处(L143-559) | ✅ |
| B1 | `processor_service.py` L185 `struct.pack('B'*N, *gpd[::-1])` | ✅ |
| B2 | `localization_service.py` L61 逐个舰长对整份 PO `re.search` | ✅ |
| B3 | `skill_service.py` L194 `SELECT DISTINCT skill_key`(每次调用全表) | ✅ |
| AP3/AP11 | `base_presenter.py` L36/48/92 无缓存解析 | ✅ |
| D2 | `kraken.py` `_bswap32`(L636)/`_byteswap`(L836) | ✅ |
| D4 | `kraken.py` `CODE_PREFIX_ORG` 定义 L409/L545/L759 三处 | ✅ |
| D5 | `extractor.py` `_match_pattern`(195)/`list_files`(217)/`_match_files`(399) | ✅ |
| D6 | `pkg_reader.py` `read_file`(122)/`extract_to_file`(194) | ✅ |
| D7 | `pkg_reader.py` `file_needs_bc7prep`(265)/`_decode_bc7prep`(291) | ✅ |
| P6 | `kraken.py` `_decode_rle`(974) | ✅ |
| U1 | `crew_customize_dialog.py` `_build_trigger_text`(143)/`_build_talent_tooltip`(211) | ✅ |
| U2 | `penetration_calculator.py` L2357 `gaussian_dispersion_points` | ✅ |
| U3 | `penetration_calculator.py` `_mod_matches`(1760) | ✅ |
| U5 | `detail_panel.py` `_proj_to_air` L2362/2554/2810 三处 | ✅ |
| U6 | `penetration_calculator.py` `_resolve_name`(803)+`firing_arc_dialog.py` `_resolve_ship_name`(516,裸 SQL L535) | ✅ |
| U9 | `penetration_calculator.py` L179 重定义 `NATION_MAP` | ✅ |
| U10 | `penetration_calculator.py` `_build_curve_chart`(1944)/`_build_dispersion_ellipse`(2295) | ✅ |
| U13 | `detail_panel.py` `_additive_keys` L1522/3443/3506 三处 | ✅ |
| AP1 | `detail_panel.py` `_on_consumable_btn_click`(3859) vs `ship_presenter.py` `_append_consumables`(566) | ✅ |
| AP2 | `ship_presenter.py` `_build_ap_pen_summary`(538)+`calculate_full_ballistics`(554) | ✅ |
| AP4 | `ship_presenter.py` L21 `MODIFIER_MAP` | ✅ |
| AP10 | `main.py` `load_stylesheet`(93)+`folder_selected` 双发射(L214/220) | ✅ |
| UA1 | `decoders.py` `build_self_id_index()` L28/192/308 三处反复重建 | ✅ |
| UA2 | `parser.py` `get_prototype_data`(183)整段切片;`service.py` `decode_path_json`(273)/`dump`(303) | ✅ |
| UA3 | `parser.py` L377 `blob = data[...]` | ✅ |
| UA4 | `parser.py` `get_string_by_id`(66)开放寻址无缓存 | ✅ |
| UA5 | `idx_parser.py` `_read_null_terminated_string`(99)+`geometry_parser.py` `_read_packed_string`(266)/`_resolve_relptr`(262)+`binary.py`(72/84/103) | ✅ |
| UA6 | `service.py` `load_from_game`(72) vs `extractor_service.py` `_extract_assets_bin`(87) | ✅ |
| 死代码 | `kraken` `_lookup`(600)/`_huff_convert_to_ranges`(366);`pkg_reader` `_load_pkg`(70)/`clear_cache`(315);`extractor` `_match_pattern`(195)/`flatten`(276);`shaders.py` 存在且零引用;`binary.py` L64/127/134/171;`types.py` L96/119/142;`decoders.decode_record`(685);`vfs.files_with_type`(341);`service.can_decode_path`(283) | ✅ |

### 5.2 复核修正

- `can_decode_path` 实际位于 `uncode_assets/service.py:283`(原报告误标为 `vfs.py:283`),已修正 1.6 表。
- `shaders.py`(359 行)确认**仍存在**于 `uncode_assets/`,全库零引用(唯一命中是本文档)。
- 其余所有位置/行号与初查一致,无其他误报。

### 5.3 复核结论

- 初查报告可信度:高(全部关键项命中,仅 1 处小位置误差)。
- 当前代码库未实施任何优化,按 Phase 0(快赢)开始实施即可。
- 建议首轮实施:B1(字节反转)、A1(穿深合并)、A6(抽方法)、UA1(索引缓存)、UA4(strings dict 化)。

---

## 六、增量复查发现(2026-08-19)

> 目的:全量再扫一遍,**找出初查报告未覆盖的新优化点**。
> ⚠️ 关键遗漏:`services/assets_cache_service.py`(612 行,**被 geometry_service 6 处 + processor_service 引用**)初查完全未覆盖,本次深审。

### 6.1 assets_cache_service.py 专属发现(AC 系列)

| ID | 位置 | 问题 | 级别 |
|---|---|---|---|
| AC1 | `populate()` 材质解析块(L307-392)≈ `uncode_assets/decoders.py::decode_material`(119-174) | **mfm 格式布局知识双份维护**(偏移/类型枚举/ptype 4/7),升级必须两处同步 | 高 |
| AC2 | `populate()` 渲染集扫描块(L249-304)≈ `decoders.decode_visual`(177-245)+`_visual_render_sets`(248-291) | 同上,渲染集/geometry 引用/damage 判定(`_crack_`/`_lod`/`Crack`)双份 | 高 |
| AC3 | 骨架 HP_ 收集(L186-195) vs `analysis_service._ship_mount_map`(380-395) | 双份;analysis 已验证只取 `*_ports` 分段省 ~60% 解码量,populate 全量遍历 | 中 |
| AC4 | `_strings_dict`(570-602) vs `GeometryService._strings_dict`(1325-1362) | **逐字一致**(连注释都同) | 中 |
| AC5 | `_material_family`(524-535) vs `GeometryService._material_family`(1454-1468) | **逐字一致**(`0x0009→indexed / 0x0005→pbs`) | 中 |
| AC6 | `_to_render_row`(604-612) vs `GeometryService._matrix_to_render`(821-828) | 同逻辑(列主序→行主序),仅返回 bytes vs ndarray | 低 |
| AC7 | `_init_core_tables_inline`(101-151) vs `resources/database/assets_database.sql` | **schema 双份**(6 表+3 索引内嵌兜底),改表易漂移 | 中 |
| AC8 | 函数内 `import numpy as np`(L159/437/455/607) | 4 次重复 import(有缓存,风格问题) | 低 |
| AC9 | `_conn` 首连块(43-48) vs 重连块(49-58) | 重复,且重连**漏 `synchronous=NORMAL`**(不一致) | 低 |
| AC10 | `has_data()`(424-431)+ meta 表 3 列 + `populate` 参数(155-156) | **死代码**:`has_data` 全库无调用;`game_version/wows_type/created_at` 只写不读 | 低 |
| AC11 | `geometry_service.py` 6 处 `AssetsCacheService()`(694/845/867/1143/1414/1486) | 每次 new 实例→每实例新 sqlite 连接(WAL PRAGMA ×N),每艘船约 6 次连接 | 高 |
| AC12 | assets.bin 定位/提取 **3 套**(geometry `_locate_assets_bin`(757-804)/`AssetsBinService.load_from_game`(45-72)/`extractor_service._extract_assets_bin`(88-131)) | 同 `list_files+read_file` 流程,但落盘路径三套不一致 | 高 |
| AC13 | 三个懒加载 AssetsBinService 副本(geometry 805-819 / analysis 294-320 / populate L158) | 各带 `_assets_tried`,数据源路径不同(behavior 不一致) | 中 |
| AC14 | `processor_service._populate_assets_cache`(280-300) 复用 `GeometryService.instance()._locate_assets_bin` | 依赖 geometry **私有方法**,跨服务私有耦合 | 中 |

### 6.2 analysis_service 新增(N 系列)

| ID | 行号 | 问题 | 级别 |
|---|---|---|---|
| N1 | L213 `Mine` vs L227 `PlaneSeaMine` | `PROJECTILE_EXT_MAP` **逐字重复条目**(table/cols/全部 fields 相同,仅 key 不同) | 中 |
| N2 | L177 `Bomb` vs L195 `SkipBomb` | 21 列配置**只差最后一个 lambda**(is_bomb 1 vs 0) | 中 |
| N3 | L601-618 vs L619-636 | store_ship 武器 HP 循环 `Artillery`/`SecondaryArtillery` 两块**逐字相同**,ATBA 为其子集 | 中 |
| N4 | L1061/1093/1114 | `_write_artillery`/`_write_atba`/`_write_secondary_artillery` **~90% 结构相同**(仅表名/列集/是否含 caliber 旋转列不同) | 中 |
| N5 | L856-861 | `_write_upgrade_info` **N+1**:每 module id 单独查 name_mappings | 中 |
| N6 | L1286-1295 | `_write_depth_charge` **N+1**:每炮按 ammo_id 单独查 | 中 |
| N7 | L981-991 | `_write_engine` **同一份 raw_data 全量扫 3 次**(收集/查速/兜底循环语义重复) | 中 |
| N8 | L495 | `has_pure_b_air` 在**外层 raw_data 循环内**计算:每命中 AB 前缀就全扫一遍 | 中 |
| N9 | L1822/1825/1827 | `startswith("PCOK") or startswith("PCOK_")` 中 `_` 变体被前者完全覆盖 | 低 |
| N10 | L1422 | `("SkipBomb" if species=="SkipBomb" else None)` 死分支(`SkipBomb` 已在 PROJECTILE_EXT_MAP) | 低 |
| N11 | L13-18 | 未使用 import:`sqlite3`/`defaultdict`/`Callable`/`Optional`/`Path` | 低 |
| N12 | L~1500 | `_v(x) if not isinstance(x,(list,tuple)) else None` 冗余判断(`_v` 本会回退) | 低 |
| N13 | L1258 | `_write_aa` **O(n²)**:循环内 `next(i for i in items if ...)` 线性重扫 | 中 |
| N14 | L1923 | `len(list((...).glob("*.json")))` 仅为计数物化整个列表 | 低 |

### 6.3 database_service 新增

| ID | 行号 | 问题 | 级别 |
|---|---|---|---|
| N15 | L767/786/806/821/850/870/887 | "空 version_code → 取最新版本"回退样板**重复 7 次** → 抽 `_resolve_vc()` | 中 |
| N16 | ~10 处 | `try/except sqlite3.OperationalError: return ...` 异常样板重复 → 装饰器/`_safe_query` | 中 |
| N17 | L895-906 | `get_stats` **N+1 计数**:对 9 类各一条 COUNT(*),一次调用 10 条 SQL → GROUP BY 单条 | 中 |

### 6.4 models/name_mapping.py 新增

| ID | 行号 | 问题 | 级别 |
|---|---|---|---|
| N18 | L9-208 vs L276-493 | `MODIFIER_MAP` 与 `MODIFIER_FORMAT_MAP` **键集 ~100% 重复**(196 vs 195,已脚本验证 FORMAT ⊆ MAP) | 高 |
| N19 | L668 vs L678 | `RIBBON_MAP` 与 `RIBBON_MAP_CREW` **键完全相同**,仅 `"13"` 一个值不同(其余 18 条逐字重复) | 中 |
| N20 | L575-595 vs L596-639 | `get_modifier_color` 与 `format_modifier` **前段逻辑重复**(早退/符号翻转/coeff 判定) | 中 |
| N21 | L~491/L~516 | "颜色方向"注释块**被整段复制错位**(误置于 MODIFIER_VALUE_FACTOR 前) | 低 |
| N22 | L252 vs L688 | `BUOYANCY_MAP` 与 `DEPTH_MAP` 部分重叠(SURFACE/PERISCOPE/DEEP_WATER/…),文案不同易混淆 | 低 |

### 6.5 cli.py ×2 新增

| ID | 位置 | 问题 | 级别 |
|---|---|---|---|
| N23 | `data_extractor/cli.py` 6 个 cmd_* | `GameExtractor(...)` + try/finally `close()` 样板重复 6 次 | 低 |
| N24 | cli L84-88 vs L149-153 | `cmd_list`/`cmd_search` 结果打印块逐字重复 | 低 |
| N25 | cli L47-48 | 未使用 import `list_files_fn`/`extract_files_fn` | 低 |
| N26 | `uncode_assets/cli.py` 8 个 cmd_* | `_make_service(args.source)` + close() 样板重复 8 次 | 低 |
| N27 | cli `cmd_resolve`/`cmd_decode`/`cmd_mfm`(×2) | `except AssetsBinError: print(❌...); sys.exit(1)` 样板重复 4 次 | 低 |
| N28 | cli L33 | `import json` 未使用,`cmd_mfm` 却用 `__import__("json")` 内联 | 低 |

### 6.6 uncode_assets/gui.py 新增

| ID | 行号 | 问题 | 级别 |
|---|---|---|---|
| N29 | L~305 | `except (AssetsBinError, KeyError, ValueError, Exception)` 元组冗余(前三类都是 Exception 子类) | 低 |
| N30 | L270 vs L344 | `_find_dir_item` 与 `_reveal_file` "按 text 沿路径找子节点"循环重复 | 低 |
| N31 | L330-348 | `_on_search` 对 `all_files()` **迭代两遍**(先文件名后路径) | 低 |
| N32 | L22 | 未使用 import `QFont` | 低 |
| N33 | L170 | `center_on_screen` **又一份**(归入已知 U4 收敛) | 低 |

### 6.7 其他次要新增

| ID | 位置 | 问题 | 级别 |
|---|---|---|---|
| N34 | `utils/qrc_rebuilder.py` L28 `_EXCLUDE` vs `scripts/gen_qrc.py` L13 `EXCLUDE` | `{"epic_skill_config.json"}` 常量双份硬编码(注释自认需手动同步) | 低 |
| N35 | `utils/theme.py` `qss()` | 每个颜色 key 对整段模板做一次 `.replace`(~30 次全量扫描) → 单次 `re.sub` | 中 |
| N36 | `models/dds_reader.py` L134 | `block_bytes = 16 if bc_kind in (2,3,6,8) else 8` 在 mip 循环内每层重算(常数) | 低 |

### 6.8 明确无新增区域

- `database_service.initialize()`/ALTER 样板、PO 解析、实体映射 → 均为已知 A2/A7/A12/A13/B7,无新点。
- `models/dds_reader.py` 除 N36 无其他;`GameParams.py`(23 行)仅 2 个极小风格点。
- `utils/theme.py` 深浅双色表属主题固有结构,不算重复。

### 6.9 增量发现与已知条目的关系

- N7/N8 属 **B8 家族新增实例**(报告只报了总括,未枚举 `_write_engine` 3 次扫、`has_pure_b_air` 循环内重算)。
- N18/N19 是**类内数据重复**,与已知 AP4(跨文件 MODIFIER 双字典)是两回事。
- N33 归入 U4;AC11/AC12/AC13 与已知 A3/A4 相关但有新细节(6 处实例化、落盘路径不一致)。

### 6.10 增量建议(纳入既有阶段)

- **Phase 0 追加**:AC10 删 `has_data`+meta 只写列(纯死代码,零风险)。
- **Phase 2 追加**:N15/N16/N17(database_service 样板与 N+1 计数)、N18/N19(name_mapping 派生)、N5/N6/N7/N13(analysis 写入 N+1 与重复扫描)。
- **Phase 3 追加**:AC4/AC5/AC6/AC7 提取共享(字符串表/技术族/矩阵转换/schema 单一来源)。
- **Phase 4/5 追加**:N23-N28(cli 样板收敛)、N35(theme qss 单次替换)、N36(dds_reader 常数外提)。
- **新增独立项**:AC11(6 处实例化合并单例)、AC12/AC13(assets.bin 定位/懒加载统一为单一 helper,消除 3 套路径与 3 份副本)、AC14(processor 改依赖共享 helper 而非 geometry 私有方法)。
