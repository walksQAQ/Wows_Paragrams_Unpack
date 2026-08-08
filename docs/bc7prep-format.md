# bc7prep 格式（Oodle Texture BC7 预处理）

> 来源实现：`data_extractor/bc7prep.py`
> 格式参考：OodleUE 2.9.15 `src/oodle2/texturert/bc7prep_decode.cpp`

## 概述

bc7prep 是 Oodle Texture 对 BC7 纹理的预处理格式：**100% 无损位重排**（无预测/残留流）。
解码输出与游戏原始 BC7 逐位一致（与 pfsunpack2 一致）。

## 文件中的位置

- DDS + DX10 头（148 字节）之后紧跟 48 字节 bc7prep 头
- version 字段位于文件 offset **148**，必须 == `0x000007BC`
- payload 从文件 offset **196** 开始（不是 192！）

## 头部布局（OodleTexRT_BC7PrepHeader，48 字节，无 padding）

| 偏移 | 类型 | 说明 |
|------|------|------|
| +0x00 | u32 | version，必须 == 0x7BC |
| +0x04 | u32 | flags |
| +0x08 .. +0x2F | u32 ×10 | mode_counts[0..9] |

## flags 位

- bit i（0..9）= mode i SPLIT（`BC7PREP_FLAG_SPLIT0` = 1）
- bit 16 = SWITCH_COLORSPACE（1 << 16）
- 其余位必须为 0

## 模式常量

- mode_sizes：mode0-8 = 16 字节，mode9 = 4 字节
- decode_split_pos（0 → 视为不 split）：
  m0=8 m1=8 m2=12 m3=12 m4=6 m5=8 m6=8 m7=12 m8=16 m9=4

## payload 布局（无 runs 数组）

依次：mode0..mode8 各 `mode_counts[i] * 16` 字节 + mode9 `mode_counts[9] * 4` 字节
最后：mode nibbles = `(num_blocks + 1) // 2` 字节，每块 4bit（低 nibble 先，按输出顺序）

```
payload_size = Σ mode_counts[i] * mode_sizes[i] + (num_blocks + 1) // 2
num_blocks   = Σ mode_counts[i]
```

## 解码流程（`bc7prep_decode`）

1. 校验 header；输出 = num_blocks × 16 字节标准 BC7
2. 计算 mode_pos 前缀和
3. split 模式数据布局：
   - **split**：数据 = [各块 part0（前 split 字节）][各块 part1]
   - **非 split**：16B/块，part1 在块内 +split 偏移
4. 按 **2048 块 chunk**：
   a. 读 nibble 排序得到各 mode 的块索引（每 nibble 字节两块，i 步进 2）
   b. 对每 mode 调 `un_munge`，用 cursor0/cursor1（**跨 chunk 累加** `+= count * advance`）
5. `un_munge` = 纯位重排（bit_extract + compact/expand 查表移位）+ 可选 YCrCb 去相关
   （R = G+Cr, B = G+Cb，modular 精确可逆）→ 组装标准 BC7 128bit（lo/hi u64 LE）
- **mode8** = 16B 原样拷贝
- **mode9** = 4B RGBA 固体色 → 展开成 mode5 块（0xaaaaaaac 模式）

## 与 BC7 mode 位对应

`un_munge` 输出 lo bit：mode0=1, mode1=0x2, mode2=0x4... 与 BC7 mode 位直接对应

- mode 识别 = 找**第一个 1**（bit0=1 → mode0）；**不是**找第一个 0
- mode8 = 首字节 0x00 保留

## 集成（`data_extractor/pkg_reader.py`）

- 检测 `data[148:152] == 0x7BC` → 解码后 `data[:148] + 像素`
- 把 DDS 头 offset40（Oodle 标记 0x1）清零（与 pfsunpack2 一致）
- DXGI：BC7_UNORM = 0x62（98），fourcc 'DX10' = 0x30315844
- 普通纹理是 DXT1/BC1 非 BC7

## 纯 Python 可行性

- ~400-800 行，逐行移植 `un_munge`（标量路径）+ 预计算 compact/expand 表
- 1024×1024（65536 块，1MB）：纯标量 ~0.3-3s，numpy 向量化 ~10-50ms
- 验证：与 pfsunpack2 输出逐块对比应 bit 完全一致（已实现，XGM134_n 逐字节一致）
