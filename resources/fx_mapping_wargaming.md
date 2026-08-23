# WG fx 坐标映射表（material_hash → fx 名）

共 161 组（shader_id 高16位 + material_hash 唯一组合）。
请为每组填写 fx 名（如 `grid_alpha.fx` / `ship_material_indexed.fx`），格式：`| 0x00010000 | 0x337DB144A9F7A335 | grid_alpha.fx |`

| shader_id高16 | material_hash | 命中数 | 代表 mfm（≤6） | fx 名（待填） |
|---|---|---|---|---|
| 0x00050000 | 0xCA3D73411950135A | 6 | OSV101_KureM_skinned.mfm, GGM037_380mm45_SK_L45_skinned.mfm, IGM500_203mm_55_triple_Clean_skinned.mfm, WGS3011_150mm_SK_L45_C_Black_Friday_skinned.mfm, WGS3010_120_50_Bofors_M42_SW_Black_Friday_Molding_skinned.mfm, LMY610_RecruitSmall.mfm | shaders/materials/pbs/ship_material_skinned.fx |
| 0x00050000 | 0xEEC20391868A4D5A | 6 | BD069_Director_Mk37.mfm, ZM690_Steering_Column.mfm, FGM533_330_52_Mle_1931_Azur_dead.mfm, BSB410_Conqueror_Colorful_DeckHouse.mfm, JM107_Binocular.mfm, FGS535_130_45_Mle_1932_quad_Azur_dead.mfm | shaders/materials/pbs/ship_material.fx |
| 0x00040000 | 0x733F843BCB0FF789 | 6 | OBI039_4.mfm, BAB004_Fairey_Swordfish_MkII.mfm, LSL001.mfm, LT002_stvol.mfm, OC018_fittings_alpha.mfm, OSC004.mfm | shaders/std_effects/PBS.fx |
| 0x00060000 | 0x0E1ED76150C70C86 | 6 | HM518_Life_Boat_blaze.mfm, 5in38_twin_outside_blaze.mfm, C042_Shipyard_in_alpha_blaze.mfm, C001_Net_alpha_blaze.mfm, ZM015_Speaker_blaze.mfm, GM853_Signal_Lamp_blaze.mfm | shaders/std_effects/blaze_ship_material.fx |
| 0x00020000 | 0x21A7C94E7E6F2F5D | 6 | AM076_Aircraft_Cran_1_wire.mfm, GM133_Torpedo_carriage_wire.mfm, ZM527_9m_cutter_wire.mfm, WSD025_Gdansk_1955_Deckhouse_wire.mfm, BSC024_Drake_1944_wire.mfm, ASC301_Jacksonville_1952_wire.mfm | shaders/materials/pbs/wire_material.fx |
| 0x00010000 | 0x4AF45D4D6FCB4781 | 6 | C007_Grid_4_alpha_skinned.mfm, C009_Grid_6_alpha_skinned.mfm, C008_Grid_5_alpha_skinned.mfm, C006_Grid_3_alpha_skinned.mfm, C005_Grid_2_alpha_skinned.mfm, C004_Grid_1_alpha_skinned.mfm | shaders/std_effects/grid_alpha_skinned.fx |
| 0x00050000 | 0x5DEE6E97DEFA194D | 6 | LNC560_military_navigation.mfm, LNR382_okinawa.mfm, LNC415_North.mfm, LNC412_North.mfm, LNR870_NavalDef.mfm, LNC158_Path_warrior.mfm | shaders/materials/pbs/landscape_multidetail_material.fx |
| 0x00050000 | 0xDA0D6E759FC31731 | 6 | AM965_Freedom_gundeck_metallic.mfm, XM201_YHSC_Soviet_S_1.mfm, XM095_Siren_Ice.mfm, XPT004_Torpedo_Evil_2.mfm, ZM524_Captain_cutter_pr371_12m.mfm, ASC048_Cleveland_1945_DeckHouse_metallic.mfm | shaders/std_effects/PBS_ship_metallic.fx |
| 0x00040000 | 0x0D33BAC2EE185EEA | 6 | LBC474_Wood.mfm, AM284_Boat_Winch.mfm, LBC474_Coffee.mfm, OMK038.mfm, LVA184.mfm, LMC213_British_banner2.mfm | shaders/materials/pbs/base_material.fx |
| 0x00060000 | 0x285FB8873FE57779 | 6 | XAF007_evil_Nosferatu_skinned.mfm, APT012_Torpedo_Space_skinned.mfm, JGM596_100mm65_Type98_Space_skinned.mfm, C022_Emissive_colors_skinned.mfm, GC501_Catapult_space_skinned.mfm, XGM034_Vivigun_skinned.mfm | shaders/std_effects/PBS_ship_emissive_skinned.fx |
| 0x00050000 | 0x45A9354E4F1ADDCF | 6 | GSB017_Gneisenau_1943_Hull.mfm, FM057_Depth_Charge_Roller_Rack.mfm, ASC068_Puerto_Rico_NY2020_Skin.mfm, GSC004_Hipper_1943_DeckHouse.mfm, ZM040_Depth_Charge_Thrower.mfm, XAF006_Lazarus.mfm | shaders/std_effects/PBS_ship.fx |
| 0x00060000 | 0x37B1273725BB3E46 | 6 | ASC046_Des_Moines_Space_DeckHouse.mfm, XSB004_Kurtz_Bugle.mfm, XM036_Antler_Stern.mfm, ZM203_Paper_Lantern.mfm, LSV070_neon_alpha.mfm, GGT536_533mm_Torpedo_Tubes_Quad_space.mfm | shaders/std_effects/PBS_ship_emissive.fx |
| 0x00040000 | 0x3F7925E2E3FD9CB7 | 6 | AAB505_TBF_Enterprise_Campaign_skinned.mfm, LMY203_Aircraft_loot_free_skinned.mfm, OVI036_snow_skinned.mfm, OVI3039_Rotterdam_skinned.mfm, LMY198_Parachute_PA_skinned.mfm, LMY129_skinned.mfm | shaders/std_effects/PBS_skinned.fx |
| 0x00010000 | 0x344CBE965F295BC2 | 6 | LMY425_Azur_Free_Glass.mfm, LC332_glass_alpha_skinned.mfm, LMY336_glass_alpha_skinned.mfm, LMY354_glass_alpha_skinned.mfm, transparent_glass_alpha_skinned.mfm, LC326_glass_alpha_skinned.mfm | shaders/materials/pbs/glass_material_skinned.fx |
| 0x00020000 | 0x7B1B1141EDB24923 | 6 | XSX001_Transylvania_Hull_wire.mfm, XSX026_Canterbury_wire.mfm, ZGT510_533mm_1N_3tubes_Lunar_wire.mfm, USB001_Yukon_1941_DeckHouse_wire.mfm, RSD002_SM_Storojevoy_1915_wire.mfm, JSB018_Yamato_1944_hull_wire.mfm | shaders/std_effects/PBS_wire.fx |
| 0x00050000 | 0x819133157CD101C2 | 6 | LMT899_alpha.mfm, LMD566_NY26_Pillar_Long_NA.mfm, OBP3447_port_skyscraper_Lights.mfm, LMD446_StarTrek_Stands.mfm, LMD124.mfm, LMD566_NY26_Pillar_Circle_Eu.mfm | shaders/materials/pbs/base_emissive_material.fx |
| 0x00050000 | 0xC240A93380F3C680 | 6 | APT004_Bliss_Leavitt_Mk7_projectile.mfm, JPR001_Type3_No1_Mk28.mfm, APT002_Torpedo_Duck_projectile.mfm, HM006_Flagbox_projectile.mfm, GPT001_Torpedo_533.mfm, GPT012_Torpedo_533_Nonomi_projectile.mfm | shaders/std_effects/PBS_ship_nodamage.fx |
| 0x00060000 | 0x925F3934C6CA75C3 | 6 | LMD503_FlagVert_H.mfm, GM6168_Color_Stripes_Dock.mfm, LMD503_FlagVert_J.mfm, LAG061_Sailor_white_02_waving.mfm, LAB002_Seagull_texanim.mfm, LMD504_FlagHor_K.mfm | shaders/materials/pbs/base_material_texanim.fx |
| 0x00060000 | 0xC3488D5F15A6E8DF | 6 | AGM553_16in50_Mk7_HW19_dead.mfm, XSB007_Protos_2_hull.mfm, XGM156_Tech_Gun_2_red.mfm, GSB026_Bismarck_Cologne_DeckHouse.mfm, FSB400_Normandie_Ludwig_hull.mfm, BSB065_Scarlet_Thunder_BirthDay_Deckhouse.mfm | shaders/materials/pbs/ship_emissive_material.fx |
| 0x00050000 | 0xB69E526A6A69F3EB | 6 | LNT037_Ridge_05.mfm, LNT037_Ridge_16.mfm, LNT037_Lushun.mfm, LNT056_AngelWings_015_city.mfm, LNT037_Ridge_02.mfm, LNT669_New_Dawn.mfm | shaders/materials/pbs_tiled/landscape_od_moss_material.fx |
| 0x00010000 | 0xA30C2474F7668421 | 6 | German_Disk_3Blade_03_alpha.mfm, German_Disk_4Blade_04_alpha.mfm, UK_Disk_2Blade_03_alpha.mfm, France_Disk_2Blade_03_alpha.mfm, France_Disk_3Blade_03_alpha.mfm, German_Disk_2Blade_01.mfm | shaders/materials/pbs/propeller_material.fx |
| 0x00060000 | 0x717C6D04A2936E51 | 6 | XGS162_Tech_secondary_gun_2_red_skinned.mfm, XM512_Secondary_Gun_Preset_skinned.mfm, YMS010_YHWM_L_1_skinned.mfm, XM1011_Laser_Focus_BtF_skinned.mfm, XGM219_203mm_SK_L56_hExplosive_blue_skinned.mfm, XGS161_Tech_secondary_gun_1_red_skinned.mfm | shaders/materials/pbs/ship_emissive_material_skinned.fx |
| 0x00050000 | 0x435DC24180CC6DAB | 6 | JGM049_356mm45_Type41_TGS_skinned.mfm, GGS062_88mm45_SK_L45_skinned.mfm, FSB006_Alsace_1945_skinned.mfm, AGA171_90mm_AA_Gun_skinned.mfm, AM629_Win_Table_skinned.mfm, RGM102_12in52_mod_1_skinned.mfm | shaders/std_effects/PBS_ship_skinned.fx |
| 0x00050000 | 0x9E2C4A5330ECFCCE | 6 | OMS042_cl0.mfm, LMP338_blaze.mfm, OMS040_Blucher.mfm, OMS042_cl7.mfm, OMS028_blaze.mfm, OMS036_director_blaze.mfm | shaders/std_effects/blaze_material.fx |
| 0x00040000 | 0xF06130C321F4E1C3 | 6 | LBI134_Factory.mfm, LBI133_a_alpha.mfm, LBI041_details_snow.mfm, OBC216_details_snow.mfm, OBC215_wall_2_snow.mfm, LBI135_wall.mfm | shaders/materials/pbs/base_building.fx |
| 0x00060000 | 0x0394736E663999B9 | 6 | LNF686_Coral.mfm, LNF692_Halloween2020.mfm, LNT016_BTH_1APRIL_04_lava_dry.mfm, LNF680_Coral.mfm, LNT001_solomon_island_09.mfm, LNT211_ChinaArpeggio2026.mfm | shaders/materials/pbs_tiled/landscape_od_emissive_material.fx |
| 0x00030000 | 0x31FD84148F7CB3EE | 6 | pillar_Meshdecal2.mfm, LYB207_Respawn2_road.mfm, LYB206_Respawn_road.mfm, LYB206_Respawn_sand2.mfm, OVP042_USS_250_1_Writings.mfm, pillar_Meshdecal3.mfm | shaders/std_effects/mesh_decal.fx |
| 0x00050000 | 0x0D33BAC2EE185EEA | 6 | OBI3167_Hamburg_blaze.mfm, OMK057_blaze.mfm, OBP007_blaze.mfm, OMK077_blaze.mfm, LMK100_blaze.mfm, OBP3499_ABSD_blaze.mfm | shaders/materials/pbs/base_material.fx |
| 0x00050000 | 0xC3488D5F15A6E8DF | 6 | XM079_Mustag_bomb_postap.mfm, AGM3052_16in45_Mk6_AzurLane_dead.mfm, BGS607_5_25in_50_RP10_Mk_Istar_BirthDay.mfm, GAS508_Ar196_AzurLane.mfm, GAF514_Ta152C_float_AzurLane.mfm, LMT997_alpha.mfm | shaders/materials/pbs/ship_emissive_material.fx |
| 0x00060000 | 0xDCB7B6E2889FCE2B | 3 | LAU004.mfm, LAU005_Herring_texanim.mfm, LAU003_Shark_BonesTest_01_2.mfm | shaders/materials/pbs/base_material_dissolve_texanim.fx |
| 0x00050000 | 0x0BBCD9D86B7D4A6C | 6 | OBP3279_port_coastal_NY.mfm, OBP3506_SharksEagles.mfm, OBI033_light_snow.mfm, LMY042.mfm, OBC3005.mfm, OSV3023_NY_alpha_1.mfm | shaders/std_effects/PBS_emissive.fx |
| 0x00040000 | 0x5FB6B45224D118C5 | 6 | LMY156_RvR_skinned.mfm, LMY241_French_DD_skinned.mfm, LMY237_French_DD_skinned.mfm, LMY231_Kronos_skinned.mfm, LMY228_Prem_skinned.mfm, LMY233_Nuke_skinned.mfm | shaders/std_effects/PBS_metallic_skinned.fx |
| 0x01050000 | 0xCB310ECAA21B2F06 | 1 | LNT2023_NY_07.mfm | shaders/materials/pbs_tiled/landscape_od_snow_ice_material.fx |
| 0x00010000 | 0xC27C514949E61967 | 6 | position_gizmo2_material_49.mfm, position_gizmo2_02_default.mfm, position_gizmo_02_default.mfm, position_gizmo2_material_47.mfm, scale_gizmo_02_default.mfm, position_gizmo_material_47.mfm | shaders/system/gizmo.fx |
| 0x00040000 | 0xDF29711464F5855D | 6 | LNF717_USS_Enterprise_Barge_Pack1_Floor.mfm, LNF717_USS_Enterprise_Cabin_Pack3_M.mfm, LNF730_ST_Port_chrome2.mfm, LC371Alpha_NY_Independence26_Statue.mfm, LC357_NY_Independence26_Bridge1.mfm, LNF719.mfm | shaders/materials/pbs/base_baked_lighting_dual.fx |
| 0x00020000 | 0x4EFFCA06551DF76C | 6 | VGM3030_120mm_50_Bofors_M50_PAM_DD_EA_wire_skinned.mfm, GSA010_Parseval_TF_Starscream_Deckhouse_wire_skinned.mfm, WM654_Antenna_wire_skinned.mfm, GSA002_Rhein_1945_wire_skinned.mfm, Italy_wiresatlas_wire_skinned.mfm, JGM834_457mm50_2_RF_EA_wire_skinned.mfm | shaders/materials/pbs/wire_material_skinned.fx |
| 0x00050000 | 0x0FC1E2A6C121088D | 6 | LNT028_NavalMission_100.mfm, LNT028_NavalMission_07.mfm, LNT028_NavalMission_010_city.mfm, LNT028_NavalMission_013_city.mfm, LNT040_Rock.mfm, LNT201_StarTrek_14.mfm | shaders/materials/pbs_tiled/landscape_od_sand_material.fx |
| 0x00040000 | 0x34B7DD23E86D13D4 | 6 | LMY614_Black_Friday_Free.mfm, LMY339_skinned.mfm, OVA360NY2023_skinned.mfm, LVR053_skinned.mfm, OSV100_StarTrek_skinned.mfm, LAG054_winterwoman_01_Skin_skinned.mfm | shaders/materials/pbs/base_material_skinned.fx |
| 0x00050000 | 0xCF8ECB8644B28356 | 6 | LNR731_gold_harbor.mfm, LNF555.mfm, LNC781_USS_CL.mfm, LNC230_Estuary.mfm, LNC786_USS_CL.mfm, LNR543_Shoreside.mfm | shaders/std_effects/PBS_landscape_detail.fx |
| 0x00040000 | 0x45A9354E4F1ADDCF | 6 | BSA006_Hermes_1941.mfm, JSB018_Yamato_1944_deck.mfm, ASA012_Lexington_1944_Bulbous.mfm, AM056_Boat.mfm, ASB012_North_Carolina.mfm, JM112_Gun_Deck_3.mfm | shaders/std_effects/PBS_ship.fx |
| 0x00010000 | 0x802D1E45AFB682CD | 6 | OC777_transparent_glass_alpha.mfm, transparent_glass_alpha.mfm, OVI060_Crane_Type42_glass_skinned.mfm, GSD028_Z23_Barbarossa_glass_alpha.mfm, LNF728_BDay_2024_glass.mfm, AAF804_F4U_1D_Corsair_glass_alpha.mfm | shaders/materials/pbs/glass_material.fx |
| 0x00050000 | 0x78748CBCBD34A618 | 6 | LMD434_Robot_skinned.mfm, OVI060_Crane_Type42_Red_skinned.mfm, LMD159_skinned.mfm, OC019_flags_skinned.mfm, LMY392_Blue_Archive_1_skinned.mfm, LNF728_BDay_2024_Unique_skinned.mfm | shaders/materials/pbs/base_emissive_material_skinned.fx |
| 0x00050000 | 0x925A060083441454 | 6 | BGA008_2_pdr_MkVIII_8barrel.mfm, CM126_Cleat.mfm, CM006_Anchor_2.mfm, CM156_Fire_Fighting_Gear.mfm, BGA004_12mm62_HI.mfm, GM278_GermanArc2020_YHBM_M_1.mfm | shaders/materials/pbs/ship_camo_preview_material.fx |
| 0x00050000 | 0x39CB3A5C625A58E3 | 6 | LNR847_s01_NavalBase.mfm, LNF244_Halloween.mfm, LNF242_Halloween.mfm, LNF247_Halloween.mfm, LNF246_Halloween.mfm, LNF243_Halloween.mfm | shaders/std_effects/PBS_landscape_detail_sss.fx |
| 0x00010000 | 0xEB0FC2B12348297E | 1 | entity_arrow_empty_skinned.mfm | shaders/std_effects/lightonly_skinned.fx |
| 0x00060000 | 0x8DFD86BCE980C98F | 6 | OGM3033.mfm, OGM3102.mfm, OGM3025_North.mfm, OGM3035.mfm, LMK_033.mfm, OGM3056.mfm | shaders/std_effects/legacy_blaze_material.fx |
| 0x00010000 | 0x337DB144A9F7A335 | 6 | C004_Grid_1_alpha.mfm, C001_Net_alpha.mfm, LSV301_Boomin_Beaver_Net.mfm, C005_Grid_2_alpha.mfm, C006_Grid_3_alpha.mfm, FSC401_Brest_1944_BA_Grid.mfm | shaders/std_effects/grid_alpha.fx |
| 0x00050000 | 0x2CFE2A8648CC79A9 | 6 | ZGM500_5in38_Mk30_China_NY_skinned.mfm, XAD004_evil_metalic_skinned.mfm, XAF004_evil_float_skinned.mfm, AGS528_Mk8_skinned.mfm, RGM570_130mm_B13_2c_Siegebreaker_skinned.mfm, ZM200_Misc_Atlas_skinned.mfm | shaders/std_effects/PBS_ship_metallic_skinned.fx |
| 0x00060000 | 0x39C617D5FB012CE1 | 6 | LNF450_FA_2019_Estuary.mfm, LNF457_FA_2019_Estuary.mfm, LNF595_HalloweenGate.mfm, LNF455_FA_2019_Estuary.mfm, LNF458_FA_2019_Estuary.mfm, LNF456_FA_2019_Estuary.mfm | shaders/std_effects/PBS_landscape_detail_metallic_emissive.fx |
| 0x00050000 | 0xBAA3422A0ABB73AB | 6 | LNT040_Landscape1.mfm, LNT046_estuary_17_piramide.mfm, LNR522_Sestri_Ponente.mfm, LNT056_AngelWings_009_coast.mfm, LNT001_solomon_island_07.mfm, LNT001_solomon_island_06_Shipyard_Wisconsin.mfm | shaders/materials/pbs_tiled/landscape_od_moss_sand_material.fx |
| 0x00040000 | 0x819133157CD101C2 | 6 | LNF631_HBD2019_PART_2.mfm, OBI088_Kure_v2.mfm, OBI3084_Kure_v2.mfm, OBI032.mfm, OGB001_North.mfm, OBI029.mfm | shaders/materials/pbs/base_emissive_material.fx |
| 0x00070000 | 0x4E3A4503A403CC19 | 6 | LNF373_April18.mfm, LNF370_meteor.mfm, LNF378_April18.mfm, LNF371_April18.mfm, LNF372_April18.mfm, LNF383_April18.mfm | shaders/std_effects/asteroid.fx |
| 0x00050000 | 0xCB310ECAA21B2F06 | 6 | LNT033_NewTierra_04.mfm, LNT205_Shipyard_Blucher.mfm, LNT054_IceMap_14_snow.mfm, CEM021_CliffIce.mfm, LNT054_IceMap_06.mfm, LNT203_Shipyard_Niord_Snow_1.mfm | shaders/materials/pbs_tiled/landscape_od_snow_ice_material.fx |
| 0x00020000 | 0xED30C78908F174AE | 6 | Minion_Hologram_holographic.mfm, TF_Autobot_Hologram_dead_alpha_holographic.mfm, GSA009_Parseval_Brunhild__fon_alpha_holographic.mfm, XGS188_Tech_Consumable_1_blue_alpha_holographic.mfm, Transformers_Hologram_dead_holographic.mfm, TF_Transformers_Hologram_dead_alpha_holographic.mfm | shaders/std_effects/holographic.fx |
| 0x00010000 | 0x1B4A994EE8B3A450 | 6 | graph_link_03_default.mfm, radius_gizmo_small_03.mfm, unit_sphere_lambert1.mfm, hemisphere_gen_shadow.mfm, graph_add_03_default.mfm, scale_gizmo_uv_material_47.mfm | shaders/std_effects/lightonly_alpha.fx |
| 0x00050000 | 0xD3C421F9C9D23A71 | 6 | WPD007_Depth_Charge_Arbor_projectile.mfm, JPT023_Sea_Torpedo_610mm_Type8_Black_projectile.mfm, JPB009_No3_Mod2_32kg_projectile.mfm, JPT103_Golden.mfm, RM184_Depth_Charge_Shelving_BM1_projectile.mfm, WPT004_Torpedo_Fiume_MKIII_450_AW_projectile.mfm | shaders/materials/pbs/ship_nodamage_material.fx |
| 0x00050000 | 0x8D2F3DC48069392A | 6 | LNU046_estuary_11.mfm, LNU015_NE_NORTH_05.mfm, LNU003.mfm, LNU034_UnderWater.mfm, LNU028_NavalMission_05.mfm, LNU001_USS_CL01.mfm | shaders/materials/pbs_tiled/landscape_od_ns_material.fx |
| 0x00050000 | 0x813FC89DD93125EC | 6 | LNU736_Advance.mfm, LNU732_Advance.mfm, LNU730_Advance.mfm, LNU609_s09LePVE.mfm, LNU601_s09LePVE.mfm, LNU633_s06_Atoll.mfm | shaders/materials/pbs_tiled/landscape_od_material.fx |
| 0x00000000 | 0x75C8053F0B695777 | 6 | OMS020_Anchorage_stage_16.mfm, OMS020_Anchorage_stage_14.mfm, WaterOcclusion.mfm, WaterOcclusion.mfm, LBP089_Shipyard_Niord_WATEROCCLUDER.mfm, WaterOcclusion.mfm | shaders/std_effects/water_occluder.fx |
| 0x00000000 | 0xCD52DCD34E66E0A9 | 4 | LMD500_water_Blucher1.mfm, simple_water.mfm, simple_water.mfm, LMD501_water_Blucher2.mfm | shaders/std_effects/simple_water.fx |
| 0x00020000 | 0xBCDBE9A539AE8AB2 | 1 | Warp.mfm | shaders/screen_effect/warp.fx |
| 0x00030000 | 0xA602D922758A13E5 | 1 | TF_Transformers_Hologram_alpha_holographic_skinned.mfm | shaders/std_effects/holographic_skinned.fx |
| 0x00060000 | 0x3C01ED12B4B7A0BC | 6 | LNF425_AzurLane_Ceiling.mfm, LNF496_e06.mfm, LNF407_AzurLane_Billiards.mfm, LNF410_AzurLane_Window.mfm, LNF476_1sApril2019.mfm, LNF472_1sApril2019.mfm | shaders/std_effects/PBS_landscape_detail_emissive.fx |
| 0x00010000 | 0x6556D942FA22D9E3 | 6 | MY009_marker_convoy_tim0_dmat_marker.mfm, basic_entity_arrow_empty.mfm, hemisphere_rotate.mfm, MY008_marker_convoy_tim1_dmat_marker.mfm, hemisphere_red.mfm, directional_arrow_empty.mfm | shaders/std_effects/lightonly.fx |
| 0x00050000 | 0x29275B0CC604A7EA | 3 | LNR693_ice_islands.mfm, LNR691_ice_islands.mfm, LNR696_ice_islands.mfm | shaders/materials/pbs/landscape_detail_sss_material.fx |
| 0x00030000 | 0x3A8CC900E6078ED9 | 6 | LMP265_Aviere.mfm, LMP292_NY.mfm, LMP270.mfm, LMD084_Zippangu.mfm, LMP281.mfm, LMP275_Marseille.mfm | shaders/materials/pbs/thin_material_texanim.fx |
| 0x00020000 | 0x20EC8537199C13A3 | 6 | RRS084_P10_wire_skinned.mfm, JSA009_Ryujo_1933_wire_skinned.mfm, FSB025_Bourgogne_1945_Hull_wire_skinned.mfm, GSA001_Graf_Zeppelin_1945_hull_wire_skinned.mfm, ASA033_Roosevelt_Clanes_Hull_wire_skinned.mfm, BSA007_Indomitable_1944_wire_skinned.mfm | shaders/std_effects/PBS_wire_skinned.fx |
| 0x00050000 | 0xA42CFD6B193891AB | 6 | LNT044_PW_24.mfm, LNT2023_NY_04.mfm, LNT033_NewTierra_05.mfm, LNT2023_NY_06_NY24.mfm, LNT044_PW_12.mfm, LNT044_PW_03.mfm | shaders/materials/pbs_tiled/landscape_od_moss_snow_material.fx |
| 0x00050000 | 0x0D3C44FE186039BB | 6 | OMC178_Shark_skinned.mfm, OVP118_5_skinned.mfm, CH003_Swob_Space_skinned.mfm, LMY146_HW2018_skinned.mfm, OMP112_skinned.mfm, LMY147_HW2017_skinned.mfm | shaders/std_effects/PBS_skinned_emissive.fx |
| 0x00020000 | 0xA602D922758A13E5 | 6 | CEM018_NY_Moray_Eel_underbow.mfm, LMY316_logh_2_holographic_skinned.mfm, XM1011_Laser_Focus_BtF_B_alpha_holographic_skinned.mfm, C012_Glass_alpha_holographic_skinned.mfm, TF_Megatron_Hologram_alpha_holographic_skinned.mfm, CEM018_NY_Moray_Eel.mfm | shaders/std_effects/holographic_skinned.fx |
| 0x00060000 | 0x26CB5105050325A4 | 6 | AM486_Fairlead_blaze.mfm, GF034_10_5m_Forteop_Rangefinder_blaze.mfm, CM146_Emergency_Box_Ice_blaze.mfm, AM485_Fairlead_blaze.mfm, GGM057_149mm60_DrhTr_C25_blaze.mfm, BGM056_14in45_BL_MkVII_Quadro_blaze.mfm | shaders/std_effects/blaze_PBS_ship.fx |
| 0x00040000 | 0xCAD8702825EBCD55 | 6 | LBC474_BDAY25_Props3_Cap.mfm, LMD552_Car1.mfm, LMD544_ToyR42_Zone6.mfm, LNF717_USS_Enterprise_Barge_Pack2_Unique_skinned.mfm, LMD529_PosterPinup.mfm, LMD526_Planets.mfm | shaders/materials/pbs/base_baked_lighting_dual_skinned.fx |
| 0x00040000 | 0xC7D21C92016CFC14 | 5 | LMY357_1_skinned.mfm, LMY406_Star_Trek_Collection_Prem_Display_alpha_skinned.mfm, LMY401_psplive_Prem_Display_alpha_skinned.mfm, LMY385_StarTrek_Slideshow_skinned.mfm, LMY365_BEG_HB2023.mfm | shaders/std_effects/slideshow_skinned.fx |
| 0x00040000 | 0xCA3D73411950135A | 1 | JGA518_13mm76_Type93_double_HW19_skinned.mfm | shaders/materials/pbs/ship_material_skinned.fx |
| 0x00050000 | 0x3A8CC900E6078ED9 | 6 | WM970_Greek_Flag_01_1.mfm, GM257_1.mfm, LMD068_1.mfm, AM1534.mfm, LMP290_NY_1.mfm, WM971_Greek_Flag_02_1.mfm | shaders/materials/pbs/thin_material_texanim.fx |
| 0x00050000 | 0xEC84E2BF1FCD2DE6 | 6 | XM097_MidFront_Scharnhorst_Frost.mfm, BSB022_Duke_of_York_frost_DeckHouse.mfm, BSB022_Duke_of_York_frost.mfm, GSB022_Scharnhorst_Frost_deckHouse.mfm, GSB022_Scharnhorst_Frost.mfm, XM418_Gun_Ice_1.mfm | shaders/std_effects/PBS_ship_sss.fx |
| 0x00040000 | 0x24BF66FA6CAAF77A | 6 | LMD408_LSCAR6.mfm, LMD465_ST_LaptopScreen.mfm, LMD408_LSCAR.mfm, LNF716_HB2023_Part2_Disp4.mfm, LNF716_HB2023_Part3_Disp2.mfm, LNF728_BDay_2024_Screens.mfm | shaders/std_effects/slideshow_transparent.fx |
| 0x00040000 | 0xEEC20391868A4D5A | 6 | 06_copper.mfm, 21_ice.mfm, AGA550_40mm_Bofors_HW19_dead.mfm, 22_canvas.mfm, 10_iron.mfm, Roughness_test_2.mfm | shaders/materials/pbs/ship_material.fx |
| 0x00050000 | 0x6D6A0AEFC641028A | 6 | LNS034_UnderWater.mfm, LNT055_SEYCHELLES_07.mfm, LNT055_SEYCHELLES_01.mfm, LNT055_SEYCHELLES_08.mfm, LNT055_SEYCHELLES_04.mfm, LNT520_Lushun.mfm | shaders/materials/pbs_tiled/landscape_od_dual_material.fx |
| 0x00040000 | 0x0B68E2F6F6251910 | 6 | LMY247_French_DD_Safe.mfm, LMY272_Soviet_Safe_metallic.mfm, OL3263_ChinaArpeggio2018.mfm, LVP117_Montgolfier_metallic.mfm, LMY205_British_arc_Safe.mfm, LMY184_Safe.mfm | shaders/std_effects/PBS_metallic.fx |
| 0x00040000 | 0x435DC24180CC6DAB | 6 | cat_sam_skinned.mfm, IGA022_37mm_Breda_barrels_4_skinned.mfm, RGS083_100mm_B_34_USM_skinned.mfm, IGS057_88mm45_SK_L45_skinned.mfm, OVI021_skinned.mfm, LVI023_skinned.mfm | shaders/std_effects/PBS_ship_skinned.fx |
| 0x00040000 | 0x834BA4713ED51486 | 6 | LBC069_doors_windows_snow.mfm, LBC069_doors_windows.mfm, LBC069_doors_windows_snow_lights.mfm, LBC069_doors_windows_lights.mfm, OBI003_Wall_01.mfm, LBC471_NY_Mail.mfm | shaders/materials/pbs/base_emissive_building.fx |
| 0x00050000 | 0x37B1273725BB3E46 | 3 | XM903_Cleveland_SpaceDecor.mfm, LMS014_Bonny_Emissive_colors.mfm, LMS015_Evil_Rampfish.mfm | shaders/std_effects/PBS_ship_emissive.fx |
| 0x00060000 | 0x16385EB04616E585 | 3 | LNF995_Jacuzzi_Palm.mfm, LNF995_Jacuzzi_Monstera.mfm, LMD547_Flag_R42_Round_02.mfm | shaders/materials/pbs/base_baked_lighting_dual_texanim.fx |
| 0x00040000 | 0x925F3934C6CA75C3 | 6 | LMP314_1_Talk.mfm, LMP309_Talk.mfm, LMP314_Talk.mfm, LMP314.mfm, LMP309_Talk_2.mfm, LMP311_Talk.mfm | shaders/materials/pbs/base_material_texanim.fx |
| 0x00040000 | 0x925A060083441454 | 6 | GM021_Flag.mfm, BGS055_5_25in_50_QF_MK_I.mfm, AGS038_5in38_Mk30_Mod1.mfm, AGS057_5in38_Mk40_Mod33.mfm, BRF036_Anemometer.mfm, BD016_HACS_MK_IV_RD15ft.mfm | shaders/materials/pbs/ship_camo_preview_material.fx |
| 0x00050000 | 0x47F750F856D869D4 | 6 | XM451_Duck_body_WildWest.mfm, XM453_Duck_body_Zorro.mfm, XM454_Duck_Turret_Zorro.mfm, XM449_Duck_body_Soldier.mfm, XM445_Duck_body_Policeman.mfm, XM455_Duck_body_Terminator.mfm | shaders/materials/pbs/ship_translucent_material.fx |
| 0x00040000 | 0xDA5B5904CF632411 | 6 | OSL040_LunarNY2026_Dragon.mfm, LNF991_TV.mfm, LNF993_Jacuzzi.mfm, LMP310.mfm, LNF716_HB2023_Part3_Disp1.mfm, LNF718_USS_Enterprise_Cabin_Display3.mfm | shaders/std_effects/slideshow.fx |
| 0x01050000 | 0xA42CFD6B193891AB | 1 | LNT033_NewTierra_21.mfm | shaders/materials/pbs_tiled/landscape_od_moss_snow_material.fx |
| 0x00030000 | 0x163EE074E8680C26 | 1 | CY001_LoopedFlag.mfm | shaders/std_effects/flag.fx |
| 0x00060000 | 0x6897A19EDC616EBB | 6 | LMT779_Hallowen2020_Portal_Emissive.mfm, LMT273_StarTrek_02.mfm, LMT273_StarTrek_03.mfm, LMT780_Hallowen2020_Portal.mfm, LMT784_Hallowen2020_G.mfm, LMT779_Hallowen2020_Portal.mfm | shaders/materials/pbs_tiled/landscape_od_dual_emissive_material.fx |
| 0x00000000 | 0xDC3078502D8D711F | 1 | LK006_sphere_moving.mfm | shaders/environment/cubemap_sky_box_with_fog.fx |
| 0x00040000 | 0xDA0D6E759FC31731 | 6 | CM077_Propeller_PL_3_R.mfm, CM136_Telegraph.mfm, FSB015_Gascoigne_1941_3D_skin_Royal.mfm, XM223_YHGH_Soviet_M_1.mfm, FSB015_Gascoigne_1941_3D_skin_Royal_Deckhouse.mfm, XM276_YM003_FranceArc_Atlas.mfm | shaders/std_effects/PBS_ship_metallic.fx |
| 0x00020000 | 0x0973CC18A1AC45CF | 6 | LNG007_Aurora_2.mfm, LNG009_Aurora3_inside.mfm, LMD443_AuroraBD2024.mfm, LMD475_ST_Aurora.mfm, LNG008_Glow3.mfm, LNG009_Aurora3.mfm | shaders/materials/pbs/aurora_material.fx |
| 0x00050000 | 0x91611373B7AB4F46 | 6 | LNT020_two_brothers_13_city.mfm, LNT020_two_brothers_17_city.mfm, LNT020_two_brothers_12_city.mfm, LNT020_two_brothers_06.mfm, LNR524_Shipyard_Laffey.mfm, LNT020_two_brothers_18_city.mfm | shaders/materials/pbs_tiled/landscape_od_dual_moss_material.fx |
| 0x00050000 | 0x0DC25D0A0EB4B7A8 | 2 | CEM020_Ice.mfm, LNT000_Dock_Fjords_Barge_skinned.mfm | shaders/materials/pbs_tiled/landscape_od_snow_ice_material_skinned.fx |
| 0x00070000 | 0x3B9780D9F38FA997 | 6 | LAU004_Pinata.mfm, LMD401_alpha.mfm, LMD402_Flagpole_alpha.mfm, LMD217.mfm, LMD399_pinata_tail.mfm, LAG020_alpha.mfm | shaders/materials/pbs/base_emissive_material_texanim.fx |
| 0x00060000 | 0x828C8526D7278D9F | 5 | LMT120_skinned.mfm, LMT122_AzurLane_Clock_skinned.mfm, LNF451_FA_2019_Estuary_skinned.mfm, LYB048_PA_2019_Building_01_skinned.mfm, LMT121_AzurLane_Mouse.mfm | shaders/std_effects/PBS_landscape_detail_metallic_emissive_skinned.fx |
| 0x00010000 | 0xEEC20391868A4D5A | 1 | HM6010_Kupus_Bow_Kots.mfm | shaders/materials/pbs/ship_material.fx |
| 0x00070000 | 0xFAE1D7D2C2E2BB56 | 3 | GM6191_Canvas_Stern_H_Bismarck.mfm, GM6205_Cartridges_MB_H_Bismarck.mfm, GM6204_Cartridges_MF_H_Bismarck.mfm | shaders/materials/pbs/ship_material_texanim.fx |
| 0x00000000 | 0x24BEEB553FA207CB | 6 | LMY028_map_border_16x16.mfm, LMY047_map_border_4x4.mfm, LMY045_map_border_6x6.mfm, LMY025_map_border_10x10.mfm, LMY030_map_border_20x20.mfm, LMY029_map_border_18x18.mfm | shaders/std_effects/map_border.fx |
| 0x00040000 | 0xCB67D827DB69680D | 1 | CPA001_Shell_Main.mfm | shaders/std_effects/trails/shell_tracer_body.fx |
| 0x00010000 | 0x66C780CBBABE64AE | 1 | friction.mfm | shaders/std_effects/trails/shell_tracer_friction_dual.fx |
| 0x00010000 | 0x5D9F31D0E8EC113E | 1 | head.mfm | shaders/std_effects/trails/shell_tracer_friction_head_dual.fx |
| 0x01050000 | 0x0FC1E2A6C121088D | 2 | LNT201_StarTrek_02_maps.mfm, LNT201_StarTrek_02.mfm | shaders/materials/pbs_tiled/landscape_od_sand_material.fx |
| 0x00040000 | 0x220BF1B9671AE1A8 | 2 | LNT207_Shipyard_GER_ZH1.mfm, TIL_000_landscape.mfm | shaders/materials/pbs_tiled/landscape_material.fx |
| 0x00050000 | 0x8DFD86BCE980C98F | 1 | LC031_fence_alpha.mfm | shaders/std_effects/legacy_blaze_material.fx |
| 0x00010000 | 0x6B9D948774AE264E | 2 | LNF431_PostApoc_19.mfm, LNF344_Halloween_17.mfm | shaders/std_effects/filth_small_fire.fx |
| 0x00010000 | 0xDE6505645AD9EA81 | 2 | LNF429_PostApoc_19.mfm, LNF341_Halloween_17.mfm | shaders/std_effects/filth_twist.fx |
| 0x00040000 | 0xC240A93380F3C680 | 4 | ZPD005_Depth_Charge_MK6.mfm, ZPD003_Depth_Charge_BM1.mfm, ZPD002_Depth_Charge_BB1.mfm, ZPD006_Depth_Charge.mfm | shaders/std_effects/PBS_ship_nodamage.fx |
| 0x00060000 | 0xFAE1D7D2C2E2BB56 | 1 | AM6020_Essex_Paper_Pinata_alpha.mfm | shaders/materials/pbs/ship_material_texanim.fx |
| 0x00020000 | 0x268AC19BC35505F7 | 2 | LNG007_Cloud_2.mfm, LNG007_Cloud_1.mfm | shaders/materials/pbs/cloud_plane_material.fx |
| 0x00000000 | 0x375EEAD284A5CB62 | 1 | FLATCOLOR.mfm | shaders/std_effects/flat_color.fx |
| 0x00030000 | 0xB0CC840C858C5772 | 1 | BDay2024_Warp.mfm | shaders/screen_effect/BDay2024_Warp.fx |
| 0x00050000 | 0xC72577F18E694E7A | 2 | LNU054_Faroe_01.mfm, LNU056_AngelWings_021.mfm | shaders/materials/pbs_tiled/landscape_od_ns_dual_material.fx |
| 0x00050000 | 0xF6E2E6945D9F8F7A | 5 | LNF560_PA_2019_Building_01.mfm, LNF564_PA_2019_Road_01.mfm, LMT576_PA_2019_destroy_alpha.mfm, LNF581_Nuke.mfm, LNF581_Concrete.mfm | shaders/std_effects/PBS_landscape_detail_metallic.fx |
| 0x00010000 | 0x2316D962FAB99B9A | 6 | LMT180_HW_Spiral.mfm, LMT185_HW2023_SmallFog.mfm, LMT184_HW2023_Fog.mfm, LMT182_HW_Ray.mfm, LMT181_HW_Fog.mfm, LMT181_HW_FogModel.mfm | shaders/std_effects/filth.fx |
| 0x00050000 | 0x55F0796FF0218AF8 | 5 | LNR473_new_tierra_1.mfm, LNR473_new_tierra.mfm, LNR477_new_tierra.mfm, LNR472_new_tierra.mfm, LNR471_new_tierra.mfm | shaders/materials/pbs/landscape_multidetail_sss_material.fx |
| 0x00010000 | 0x13FF117CD55EE0CD | 6 | LNT016_BTH_1APRIL_03_lava.mfm, LNT016_BTH_05_lava.mfm, LNT016_BTH_1APRIL_05_lava.mfm, LNT054_IceMap_16_lava.mfm, LNT016_BTH_1APRIL_06_lava.mfm, LNT016_BTH_03_lava.mfm | shaders/materials/pbs/waterfall_material.fx |
| 0x00040000 | 0xF581BEE306B33C7E | 2 | BPM006_Sea_Mine_field2dFloating.mfm, WM021_Torpedo_trolley_SW_field2dFloating.mfm | shaders/std_effects/PBS_field2d_floating.fx |
| 0x00010000 | 0x2B552B96F57223F7 | 2 | LNF432_CIRCLE_TEST.mfm, LNF342_Halloween_17.mfm | shaders/std_effects/filth_big_fire.fx |
| 0x00070000 | 0xC3488D5F15A6E8DF | 3 | FSD024_Le_Fantasque_Pirate.mfm, ASC064_Alaska_Skin_Deckhouse.mfm, ASC064_Alaska_Skin.mfm | shaders/materials/pbs/ship_emissive_material.fx |
| 0x00010000 | 0xC233E8990488223A | 6 | LNC241_Estuary.mfm, LNF234_ChinaArpeggio.mfm, LNF233_ChinaArpeggio.mfm, LNR002_waterfall.mfm, LNT046_estuary_19_waterfall.mfm, LNF573_PA_Waterfall.mfm | shaders/std_effects/waterfall.fx |
| 0x00010000 | 0x7A71C2D3660ABDD1 | 1 | LNF343_Halloween_17.mfm | shaders/std_effects/filth_ray.fx |
| 0x00040000 | 0x0BBCD9D86B7D4A6C | 1 | LGB100_military_snow.mfm | shaders/std_effects/PBS_emissive.fx |
| 0x00050000 | 0x754BA56487A8D1CE | 1 | LNF241_Halloween_skinned.mfm | shaders/std_effects/PBS_landscape_detail_sss_skinned.fx |
| 0x00040000 | 0x96F25FF8035156B5 | 1 | LMY153_Ice_alpha_skinned.mfm | shaders/std_effects/PBS_skinned_sss.fx |
| 0x01050000 | 0xB69E526A6A69F3EB | 3 | LNT666_New_Dawn1.mfm, LNT664_New_Dawn_Shipyard_Wisconsin.mfm, LNT664_New_Dawn.mfm | shaders/materials/pbs_tiled/landscape_od_moss_material.fx |
| 0x00050000 | 0x60CCB8DCA7B405D4 | 6 | VGM500_straw_alpha.mfm, GM256_Pine_alpha.mfm, VSD002_Jurua_Serpent_Other_alpha.mfm, IM251_Plume_ItalianArc2021_alpha.mfm, ZSA002_Sanzang_Lunar_Hull.mfm, ASC071_Atlanta_Summer_Sale_Hull.mfm | shaders/materials/pbs/ship_sss_material.fx |
| 0x00050000 | 0x733F843BCB0FF789 | 1 | OBP3448_port_NY.mfm | shaders/std_effects/PBS.fx |
| 0x00050000 | 0x1FD70AA48A12306C | 2 | ZSA002_Sanzang_Lunar_Hull_skinned.mfm, ASC071_Atlanta_Summer_Sale_Deckhouse_alpha_skinned.mfm | shaders/materials/pbs/ship_sss_material_skinned.fx |
| 0x00030000 | 0x21A7C94E7E6F2F5D | 6 | ASB088_Louisiana_EA22_wire.mfm, ASB086_Nebraska_EA22_Hull_wire.mfm, VRS032_Radar_Mk8_wire.mfm, ASB087_Delaware_EA22_Hull_wire.mfm, VM902_Crane_Base_wire.mfm, AAD506_Douglas_BTD_1_EarlyAccess_wire.mfm | shaders/materials/pbs/wire_material.fx |
| 0x00050000 | 0x60D812F9F30951F5 | 2 | LMY350_Colorful_skinned.mfm, LMY056_EACMW.mfm | shaders/materials/pbs/base_iridescent_emissive_dual_material_skinned.fx |
| 0x00040000 | 0x6811989BB36B421C | 1 | LMP015_alpha.mfm | shaders/materials/pbs/base_torpedotarget.fx |
| 0x00040000 | 0x8E0413D4B5F8D90E | 2 | WM021_Torpedo_trolley_SW_field2d.mfm, BPM006_Sea_Mine_field2d.mfm | shaders/std_effects/PBS_field2d.fx |
| 0x00050000 | 0x885E562A1BB6B8BB | 2 | LYB047_Space_station.mfm, LYB046_1april.mfm | shaders/std_effects/PBS_emissive_obstacle.fx |
| 0x00050000 | 0xD26CFA201C83E535 | 5 | LMC310_Attraction01_snow.mfm, LNF667_Building01.mfm, OBP529_BDay1.mfm, LMC314_Attraction02_CN_garland2.mfm, LVP194_PlaneBomber_alpha.mfm | shaders/materials/pbs/base_emissive_obstacle_material.fx |
| 0x00060000 | 0x03801F4413AADA78 | 5 | LMD222.mfm, LYB056_Gates.mfm, LMT214_crowd3_Kron.mfm, LMT214_crowd2.mfm, LMT203_crowd1.mfm | shaders/materials/pbs/base_material_texanim_pivot.fx |
| 0x00070000 | 0xDCC4F5E7BB6333B7 | 3 | LNT033_NewTierra_27.mfm, LNT204_Dock_NY2026_27.mfm, LNT033_NewTierra_27_NY24.mfm | shaders/materials/pbs_tiled/landscape_od_snow_ice_material_texanim_pivot.fx |
| 0x00050000 | 0x0394736E663999B9 | 2 | LNU016_Bees_to_honey_1APRIL_06.mfm, LNU016_Bees_to_honey_1APRIL_07.mfm | shaders/materials/pbs_tiled/landscape_od_emissive_material.fx |
| 0x00050000 | 0x34B2160CB6125BEE | 2 | BPM007_Sea_Mine_alpha_field2d.mfm, BPM007_Sea_Mine_field2d.mfm | shaders/materials/pbs/base_emissive_material_field2d.fx |
| 0x00070000 | 0x37B1273725BB3E46 | 1 | XSA004_Nosferatu.mfm | shaders/std_effects/PBS_ship_emissive.fx |
| 0x00050000 | 0xAF44A5BDC61F4A5A | 2 | LYB047_Space_station_skinned.mfm, LYB046_1april_skinned.mfm | shaders/std_effects/PBS_emissive_obstacle_skinned.fx |
| 0x00050000 | 0x285FB8873FE57779 | 1 | RGM562_B2LM_2nd_skinned.mfm | shaders/std_effects/PBS_ship_emissive_skinned.fx |
| 0x00030000 | 0xC6DD5B66F70A6E65 | 1 | HM210_Code_Signal_Flags.mfm | shaders/materials/pbs/thin_material.fx |
| 0x00000000 | 0xD7A4CC54C1C11BAF | 1 | LK001_moving.mfm | shaders/environment/moving_sky_box.fx |
| 0x00040000 | 0x88B1574DB454C731 | 1 | BPM006_Sea_Mine_floating.mfm | shaders/std_effects/PBS_ship_floating.fx |
| 0x00060000 | 0x45A9354E4F1ADDCF | 1 | GM515_Admiralsboot.mfm | shaders/std_effects/PBS_ship.fx |
| 0x00050000 | 0x717C6D04A2936E51 | 1 | BGA614_40mm_Bofors_BirthDay2_skinned.mfm | shaders/materials/pbs/ship_emissive_material_skinned.fx |
| 0x00060000 | 0x3A8CC900E6078ED9 | 1 | LL353_Windmill_flag_1.mfm | shaders/materials/pbs/thin_material_texanim.fx |
| 0x00040000 | 0x3A8CC900E6078ED9 | 1 | LL353_Windmill_flag.mfm | shaders/materials/pbs/thin_material_texanim.fx |
| 0x00050000 | 0x0E1ED76150C70C86 | 1 | 15_polished_metal.mfm | shaders/std_effects/blaze_ship_material.fx |
| 0x01050000 | 0x91611373B7AB4F46 | 1 | LNR521_Sestri_Ponente.mfm | shaders/materials/pbs_tiled/landscape_od_dual_moss_material.fx |
| 0x00020000 | 0xE500272228D76A2D | 1 | LNF340_Halloween_17_ShipHL.mfm | shaders/std_effects/filth_highlight.fx |
| 0x00060000 | 0x9E2C4A5330ECFCCE | 4 | LMK118_Gun.mfm, LMK116_Turbine.mfm, LMK115_Boiler.mfm, LMK117_Generator.mfm | shaders/std_effects/blaze_material.fx |
| 0x00020000 | 0x31FD84148F7CB3EE | 1 | LVP199_USS_Indep_Writings.mfm | shaders/std_effects/mesh_decal.fx |
| 0x00020000 | 0x2316D962FAB99B9A | 1 | LNF340_Halloween_17.mfm | shaders/std_effects/filth.fx |
| 0x01050000 | 0xBAA3422A0ABB73AB | 2 | LNT001_solomon_island_08_DDay.mfm, LNT001_solomon_island_08_DDay2.mfm | shaders/materials/pbs_tiled/landscape_od_moss_sand_material.fx |
| 0x00040000 | 0x52728CD1FB017735 | 1 | LMP015_floatingTorpedotarget.mfm | shaders/std_effects/PBS_floating_torpedotarget.fx |
| 0x00040000 | 0x7E31B8860C598463 | 1 | LMP015_torpedotarget.mfm | shaders/std_effects/PBS_torpedotarget.fx |
| 0x00000000 | 0xEC97A5BCFDBD3862 | 1 | LK005_sphere_moving.mfm | shaders/environment/cubemap_sky_box.fx |
