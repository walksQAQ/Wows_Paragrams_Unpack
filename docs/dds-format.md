# DDS 纹理格式

> 涉及实现：`data_extractor/pkg_reader.py`（bc7prep 检测/解码）、`data_extractor/bc7prep.py`
> 相关：bc7prep-format.md

## 概述

游戏纹理以 DDS（DirectDraw Surface）格式存储于 PKG 容器中（container 模式，Kraken 解压）。
部分纹理为 **bc7prep 预处理**格式（Oodle Texture BC7），需解码为标准 BC7 后才能使用。

## DDS 文件布局

```
DDS_HEADER（128 字节）
  magic 4B: "DDS " (0x20534444)
  DDS_HEADER 124B
[可选] DDS_HEADER_DXT10（20 字节，当 fourcc == 'DX10' 时存在）
像素数据（块压缩 / 未压缩）
```

## DDS_HEADER（124 字节，offset 4-127）

| 偏移 | 类型 | 说明 |
|------|------|------|
| +0x00 | u32 | dwSize = 124 |
| +0x04 | u32 | dwFlags |
| +0x08 | u32 | dwHeight |
| +0x0C | u32 | dwWidth |
| +0x10 | u32 | dwPitchOrLinearSize |
| +0x14 | u32 | dwDepth |
| +0x18 | u32 | dwMipMapCount |
| +0x1C | u32[11] | dwReserved1（Oodle Texture 在 **offset 40 = dwReserved1[3]** 写 0x1 标记）|
| +0x48 | DDS_PIXELFORMAT | ddspf（32 字节）|
| +0x68 | u32 | dwCaps |
| +0x6C | u32 | dwCaps2 |
| +0x70 | u32 | dwCaps3 |
| +0x74 | u32 | dwCaps4 |
| +0x78 | u32 | dwReserved2 |

## DDS_PIXELFORMAT（32 字节，@0x48）

| 偏移 | 类型 | 说明 |
|------|------|------|
| +0x00 | u32 | dwSize = 32 |
| +0x04 | u32 | dwFlags（DDPF_FOURCC = 0x4 等）|
| +0x08 | u32 | dwFourCC（'DXT1' = 0x31545844, 'DX10' = 0x30315844, 'ATI1' = 0x31495441 等）|
| +0x0C | u32 | dwRGBBitCount |
| +0x10-0x1C | u32 ×4 | dwR / dwG / dwB / dwABitMask |

## DDS_HEADER_DXT10（20 字节）

| 偏移 | 类型 | 说明 |
|------|------|------|
| +0x00 | u32 | dxgiFormat（DXGI_FORMAT 枚举值）|
| +0x04 | u32 | resourceDimension（3 = D3D10_RESOURCE_DIMENSION_TEXTURE2D）|
| +0x08 | u32 | miscFlag |
| +0x0C | u32 | arraySize |
| +0x10 | u32 | miscFlags2 |

> DDS + DX10 头 = **148 字节**。bc7prep 头正好位于这 148 字节之后（见 bc7prep-format.md）。

## DXGI 格式（dxgiFormat 值，部分）

| 值 | 格式 |
|----|------|
| 71 (0x47) | DXGI_FORMAT_BC1_UNORM（DXT1）|
| 72 | DXGI_FORMAT_BC1_UNORM_SRGB |
| 80 (0x50) | DXGI_FORMAT_BC4_UNORM（ATI1 单通道）|
| 98 (0x62) | DXGI_FORMAT_BC7_UNORM |

## 项目中的使用

### bc7prep 检测/解码（pkg_reader.py）

- magic 检查：`data[:4] == b'DDS '`
- DX10 fourcc 检查
- **bc7prep 检测**：`data[148:152] == 0x7BC`（DDS+DX10 头之后）
- 解码后：`data[:148] + 像素`，并把 offset40（Oodle 标记 0x1）清零（与 pfsunpack2 一致）

### 实测纹理（Korabli 正式服）

| 纹理 | 格式 | 尺寸 | 用途 |
|------|------|------|------|
| diffuseMap（_a.dds）| DXT1/BC1 | 32×32（824B 占位）| INDEXED 船体主漫反射占位 |
| artMap（_art.dds）| BC7 | 512×512 | 艺术涂装叠加层 |
| tiles（albedoArray）| BC7 | 1024×1024 | 38×38 图块（真正漫反射主纹理）|
| materialIdMap（_matid.dds）| ATI1（BC4 单通道）| 4096×4096 | R 通道 = 材质 ID 0~195 |
