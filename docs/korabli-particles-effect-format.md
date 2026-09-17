# Korabli 粒子效果（EffectPrototype）文件格式

> 数据来源：`assets.bin`（PrototypeDatabase blob 5）。
> 关联实现：`uncode_assets/decoders.py::decode_effect`（尽力解析）。

---

## 1. EffectPrototype 记录（blob 5，magic 0xEB23E0AF，item_size 0x10）

### 1.1 记录布局（16 字节，小端）

```
+0x00  f32  scalar（通常 -1.0 或正数如 9.5，语义未知）
+0x04  u32  count（子节点/条目数）
+0x08  u32  relptr（基准 = blob 起点 → 本记录 OOL 区域起点）
+0x0C  u32  pad（0）
```

### 1.2 指针与 OOL 约定

- **relptr 基准 = blob 起点**（非记录起点）。依据：相邻记录的 relptr 单调递增且 OOL 区域**首尾相接、无间隙**（rec0 `0x9A90` → rec1 `0xAEAF` → rec2 `0xC2CE` → ...）。
- **OOL 区域** = `[relptr, 下一记录 relptr)`。
- OOL 内含**内嵌原始字符串**（非 strings 表，直接内联在 OOL 字节里）与重复的 16B 节点模式：`-1.0f/1.0f + u32 count + u32 偏移 + pad`。

### 1.3 内嵌字符串（实测样本）

```
particles/animated/Smoke_2_8x8.dds
particles/textures/circle_02.tga
particles/animated/SparkLine_12x1.dds
sparks
glow_0
Biggy_fire_2
```

### 1.4 解码输出（decode_effect）

| 字段 | 说明 |
|------|------|
| `scalar` / `count` / `relptr` / `pad` | 记录头部字段 |
| `ool_size` | OOL 区域字节数 |
| `embedded_strings` | OOL 内嵌可打印字符串（粒子资源路径） |
| `candidate_nodes` | 16B 对齐候选节点头（`{offset, value(f32), count, relptr, pad}`，启发式） |
| `ool_hex` | OOL 头部十六进制（前 256B） |

> 节点完整字段语义分派到 `fx` 命名空间各类（见 §2），需逐类逆向。

---

## 2. 粒子系统类型表（fx 命名空间）

粒子效果图由 EffectPrototype 组合下列原型构成（RTTI 类型名来自 exe 数据区）：

### 2.1 Action*Prototype（粒子动作，16 个）

```
ActionAlphaSetterPrototype      ActionBarrierBoxPrototype
ActionBarrierCylinderPrototype  ActionBarrierPlanePrototype
ActionBarrierSpherePrototype    ActionDampferPrototype
ActionEffectSpawnerPrototype    ActionForcePrototype
ActionJitterPrototype           ActionMagnetPrototype
ActionOrbitorPrototype          ActionResizerPrototype
ActionScalerPrototype           ActionStreamPrototype
ActionSystemCreatorPrototype    ActionTintShaderPrototype
ActionTrailSpawnerPrototype
```

### 2.2 Generator（值生成器）

```
ConstantValueGenerator    CumulativeValueGenerator
RampValueGenerator        RandomValueGenerator
ValueGeneratorPrototype
VectorGeneratorPrototype  VectorGeneratorBoxPrototype
VectorGeneratorCylinderPrototype  VectorGeneratorLinePrototype
VectorGeneratorPointPrototype     VectorGeneratorSpherePrototype
VectorGeneratorPrototypeCollection
```

### 2.3 其它 fx Prototype

```
AnimationPrototype    ColorKeyFramePrototype  ComponentPrototype
DecalSourcePrototype  DistancePrototype       EffectPrototype
EffectMetadataPrototype  EffectPresetPrototype  EmitterPrototype
FloatValueKeyFramePrototype  GeneralPrototype  IntensitiesPrototype
IntensityMetadataPrototype  IntensityPrototype  LightSourcePrototype
ParticleActionPrototype  PSPrototype（ParticleSystem）  RendererPrototype
ScalerPrototype  SystemActionPrototype  TintPrototype  TrailPrototype
ValueGeneratorPrototype  VolumePrototype
```

### 2.4 枚举

```
ActionBarrierReaction        ParticleActionType
ParticleCoordinateStyle      ParticleVolumetricsVisibilityMode
ParticlesAnimationType       SystemActionType
ValueGeneratorRampParameterType  ValueGeneratorRampSamplingType
ValueGeneratorType           VectorGeneratorType
```

### 2.5 粒子组装关系（推断）

```
EffectPrototype → EmitterPrototype[] → PSPrototype（粒子系统）
   └─ ParticleActionPrototype[]（Action*：Force/Jitter/Orbitor/Resizer/TintShader/...）
   └─ VectorGeneratorPrototype[]（初始速度/位置）
   └─ ValueGeneratorPrototype[]（Ramp/Constant/Cumulative/Random → 关键帧）
   └─ RendererPrototype / TrailPrototype（粒子轨迹）/ LightSourcePrototype
```
