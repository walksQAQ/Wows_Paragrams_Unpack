# GameParams.data 序列化格式

> 来源实现：`services/processor_service.py`、`services/GameParams.py`

## 概述

GameParams.data 是游戏参数数据库，通过 **字节逆序 + zlib 压缩 + pickle 序列化** 存储。
当前版本优先使用 `GameParams_py3.data`（py3 pickle），回退 py2 / 旧 `GameParams.data`。

## 解码流程

```
1. 读取文件全部字节
2. gpd = bytes[::-1]           # 字节逆序（byte reversal）
3. gpd = zlib.decompress(gpd)
4. data = pickle.loads(gpd, encoding='latin1')
```

## 数据结构

pickle 反序列化后是 `list` / `tuple` / `dict`：

- 若为 list/tuple：遍历元素，找到含 `''` 键且值为 dict 的 dict 作为 source_dict（Wargaming 结构）
- 若为 dict 且含 `''` 键：直接作为 source_dict
- 否则：Lesta 结构（tuple[2]），逐元素 dict 拆分

## py2 / py3 差异

- py2/py3 两文件内容 **100% 相同**（21000 实体全一致），仅序列化格式/键顺序不同
- py2 = Python2 cPickle 插入序
- py3 = Python3 pickle 按类型排序
- 解码来源列表：`["GameParams_py3.data", "GameParams_py2.data", "GameParams.data"]`（py3 优先，保留回退）
- 删除列表同样加入 `GameParams_py3.data`（修复解包后 py3 残留未删问题）

## 实体结构

- 每个实体 dict 含 `typeinfo`：`{ 'type': 'Ship' | 'Gun' | 'Projectile' | 'Aircraft' | 'Ability' | 'Modernization' | 'Crew' | 'Other' | 'Exterior' }`
- 类型分类映射：Ship / Gun / Projectile / Aircraft / Ability / Modernization / Crew / Other / Exterior
- 序列化到 JSON 时（`_GPEncode`）剔除字段：`Cameras` / `DockCamera` / `damageDistribution` / `salvoParams`

## 桩类（`services/GameParams.py`）

pickle 反序列化需要旧式类定义：`TypeInfo` / `GPData` / `GameParams` / `UIParams`

- 通过 `sys.modules['GameParams'] = _GameParamsModule` 注入，使 `pickle.loads` 能找到类定义

## 提取（data_extractor）

GameParams.data 在 PKG 中为 **stored 模式**（compression_info = 0x6），即原始数据，无需解压。
由 `data_extractor.GameExtractor.list_files(["content/GameParams*.data"])` → `extract_single` 流式写盘。
