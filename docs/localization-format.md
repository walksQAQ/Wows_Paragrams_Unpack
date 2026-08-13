# 本地化文本格式（global.mo / global.po / JSON 映射）

> 来源实现：`services/localization_service.py`

## 概述

本地化服务下载并解析 `global.mo` → `global.po` → JSON 映射文件，用于显示中文名称。
格式链：

```
游戏客户端 global.mo（GNU gettext MO 二进制）
  → polib.mofile() 解析
  → global.po（GNU gettext PO 文本格式）
  → *_names.json / skill_descriptions.json（JSON 映射，导入数据库）
```

## global.mo（GNU gettext MO 格式）

- 来源：游戏目录 `bin/<版本>/res/texts/zh_sg/LC_MESSAGES/global.mo`（优先 zh_sg，回退 zh_cn）
- 或从在线仓库下载（LocalizedKorabli / Korabli-LESTA-L10N）
- 标准 gettext MO 二进制格式，由 `polib.mofile()` 解析

## global.po（GNU gettext PO 格式）

- 由 polib 从 MO 转换保存的文本格式（`msgid` / `msgstr` 条目）
- 多行续行格式合并为单行（`_merge_po_entries` 等逻辑）
- 用于导入舰长名翻译：从数据库查询 `person_name` 在 PO 中匹配翻译

## JSON 映射文件

写入 `data_dir` 下的 JSON 文件，每类一个：

- `ship_names.json` / `guns_names.json` / `ammo_names.json`
- `consumable_names.json` / `modernization_names.json` / `plane_names.json`
- `rage_mode_names.json` / `torpedo_group_names.json`
- `module_upgrade_names.json`（命名格式 `P[国籍]U[槽位类型][编号]_[名称]`）
- `skill_names.json` / `skill_descriptions.json`

导入数据库后（`import_name_mappings` / `import_po_translations`），PO 文件会被删除。
