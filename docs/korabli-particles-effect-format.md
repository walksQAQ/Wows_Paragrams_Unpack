# Korabli 粒子效果（EffectPrototype）文件格式

> 数据来源：`assets.bin`（PrototypeDatabase blob 5，magic `0xEB23E0AF`，item_size `0x10`）。
> 结构来源：**26.11PT1 客户端 `Korabli64.exe` 的 Ghidra 反编译**（工程 `Uncode_Korabli`）。
> 实现：`uncode_assets/fx.py`（解码 / XML 渲染 / 回编码），
> 界面入口：assets.bin 浏览器「明文格式」/「导出明文」。
>
> ⚠️ 布局按**莱服（Korabli）**反编译得到，寄服（Wargaming）是另一套更小的布局；
> 两套都由 `uncode_assets/fx.py` 的布局档案（`LESTA_LAYOUT` / `WG_LAYOUT`）驱动，
> 浏览器按当前服务器的 `wows_type` 自动选用。寄服差异汇总见 §16。

---

## 1. 记录（16 字节）

```
+0x00  f32  maxEmittingDuration
+0x04  u32  systemsCount
+0x08  i64  systems              相对指针，基准 = 本记录起点
+0x10  下一条记录
```

对应反编译：`FUN_1406d9cc0`（类型 unpack 入口）→ `FUN_1406e1420`
（`{u32 count; u32 pad; i64 rel}` 数组校验）→ `FUN_1406e8da0`（单条记录）。

⚠️ 早期文档写的「relptr 基准 = blob 起点」是**错误**的：基准是**记录自身地址**。
每条记录在 blob 内的记录数组里占 16 字节，所以第 i 条的基准是 `0x10 + i*0x10`。

---

## 2. systems 区域

`systems` 指向的区域由两部分组成：

```
[ systems array ]  systemsCount × 0x210 字节（fx::PSPrototype）
[ 数据池        ]  字符串、ramp 点、动作载荷……（由各字段的相对指针引用）
```

区域长度 = 下一条记录的 `systems` 指针位置 − 本条记录的位置（最后一条到数据块末尾）。
所有正式服记录都满足 `systemsCount * 0x210 <= 区域长度`。

---

## 3. fx::PSPrototype（0x210）

| 偏移 | 类型 | 字段 |
|------|------|------|
| +0x000 | struct | `renderer`（RendererPrototype，0xD0） |
| +0x0D0 | struct | `emitter`（EmitterPrototype，0x90） |
| +0x160 | struct | `animation`（AnimationPrototype，0x40） |
| +0x1A0 | struct | `general`（GeneralPrototype，0x20） |
| +0x1C0 | struct | `distance`（DistancePrototype，0x10） |
| +0x1D0 | struct | `scaler`（ScalerPrototype，0x10） |
| +0x1E0 | String | `name` |
| +0x1F0 | 数组 | `intensities`：`{u32 count; u32 capacity; i64 rel}`（基准 = 本字段地址），元素 0x10 |
| +0x200 | 数组 | `components`：`{u32 count; u32 capacity; i64 rel}`（**基准 = 结构起点**），元素 0x10 |

反编译：`FUN_1406f3180`。

`intensities` 元素（0x10，`FUN_14070d920`）是 `fx::IntensityPrototype`：

```
+0x00  数组 configs：{u32 count; u32 capacity; i64 rel}（基准 = 本元素）→ fx::IntensityConfig 数组
```

即 `effects → 系统 → 强度通道 → 通道配置（曲线 + 标志位）`，全部逐字段可读。
各通道的**名字与取值范围**不在这里，而在同路径的 `/xxx.xml/shared`
（`EffectMetadataPrototype`，见第 15 章）。

---

## 4. RendererPrototype（0xD0）

反编译：`FUN_140703800`。

| 偏移 | 类型 | 字段 |
|------|------|------|
| +0x000 | String | textureName0 |
| +0x010 | String | textureName1 |
| +0x020 | String | particleMeshPath |
| +0x030 | ValueGen | yawRateRamp |
| +0x040 | vec3 | explicitOrientation |
| +0x04C | vec3 | customCenterOffset |
| +0x054 | f32 | spinRateYaw |
| +0x058 | f32 | spinRatePitch |
| +0x05C | f32 | spinRateRoll |
| +0x060 | f32 | spinRateYawSpread |
| +0x064 | f32 | spinRatePitchSpread |
| +0x068 | f32 | spinRateRollSpread |
| +0x06C | f32 | lightingShineness |
| +0x070 | f32 | orientationYawSpread |
| +0x074 | f32 | orientationPitchSpread |
| +0x078 | f32 | orientationRollSpread |
| +0x07C | f32 | lightingAmbient |
| +0x080 | f32 | orientationYaw |
| +0x084 | f32 | orientationPitch |
| +0x088 | f32 | orientationRoll |
| +0x08C | f32 | hideStartCos |
| +0x090 | f32 | scaleX |
| +0x094 | f32 | lightingDiffuse |
| +0x098 | f32 | lightingTransmission |
| +0x09C | f32 | lightWrapAmount |
| +0x0A0 | f32 | shadowsStrength |
| +0x0A4 | f32 | opacityMultiplier |
| +0x0A8 | f32 | hideSpeed |
| +0x0AC | f32 | softParticleDepthScale |
| +0x0B0 | enum | rotationCenter（PS_RRC） |
| +0x0B4 | enum | lightingType（PS_RLT） |
| +0x0B8 | enum | blendType（PS_RBT） |
| +0x0BC | enum | sortType（PS_RST） |
| +0x0C0 | f32 | tilingU |
| +0x0C4 | f32 | tilingV |
| +0x0C8 | bool | explicitOrientationLocal |
| +0x0C9 | bool | billboard |
| +0x0CA | bool | velocityOriented |
| +0x0CB | bool | background |
| +0x0CC | bool | flipTexcoordU |
| +0x0CD | bool | flipTexcoordV |

---

## 5. EmitterPrototype（0x90）

反编译：`FUN_140704d30`。

| 偏移 | 类型 | 字段 |
|------|------|------|
| +0x000 | ValueGen | rateGenerator |
| +0x010 | VectorGen | initialPositionGenerator |
| +0x020 | VectorGen | initialVelocityGenerator |
| +0x030 | ValueGen | sizeGenerator |
| +0x040 | ValueGen | ageScaleGenerator |
| +0x050 | ValueGen | ageScaleAuxGenerator |
| +0x060 | ValueGen | delayGenerator |
| +0x070 | ValueGen | sleepPeriodGenerator |
| +0x080 | f32 | activePeriod |
| +0x084 | f32 | inheritVelocityFactor |
| +0x088 | f32 | particleDistributionStrength |
| +0x08C | bool | snapToSeaLevel |

---

## 6. AnimationPrototype（0x40）

反编译：`FUN_1407053a0`。

| 偏移 | 类型 | 字段 |
|------|------|------|
| +0x000 | ValueGen | frameRateRamp |
| +0x010 | String | motionVectorsTexture |
| +0x020 | i32 | framesPerY |
| +0x024 | i32 | framesPerX |
| +0x028 | i32 | framesRangeBegin |
| +0x02C | i32 | framesRangeEnd |
| +0x030 | f32 | animationPeriod |
| +0x034 | f32 | motionVectorsDistortion |
| +0x038 | enum | animationType（PS_PAT） |
| +0x03C | bool | randomFrameOnly |
| +0x03D | bool | useEmissionAlphaFromMV |

---

## 7. GeneralPrototype（0x20）

反编译：`FUN_140703080`。

| 偏移 | 类型 | 字段 |
|------|------|------|
| +0x00 | i32 | capacity |
| +0x04 | i32 | maxInstancesCount |
| +0x08 | f32 | maxParticleAge |
| +0x0C | f32 | cameraAttachOffset |
| +0x10 | enum | coordinateStyle（PS_PCS） |
| +0x14 | enum | volumetricsVisibilityMode（PS_PVVM） |
| +0x18 | bool | shadowVisible |
| +0x19 | bool | reflectionVisible |
| +0x1A | bool | reducedUpdateRateEnabled |
| +0x1B | bool | useWaterCulling |
| +0x1C | bool | complexIntegrationEnabled |
| +0x1D | bool | prewarm |

---

## 8. DistancePrototype / ScalerPrototype（0x10）与配置项

反编译：`FUN_1407059f0`（两者共用同一布局）→ 每个配置项 `FUN_1407120e0`。

| 偏移 | 类型 | 字段 |
|------|------|------|
| +0x00 | f32 | maxDistance |
| +0x04 | 数组 | `configs`：`{u32 count; i64 rel}`（**紧凑形式**，rel 基准 = 结构起点），元素 0x20 |

> ⚠️ 这里是全格式里**唯一**的紧凑数组形式：`count` 在 +0x04、`rel` 紧跟其后 +0x08，
> 中间没有 capacity 槽。其余数组都是 `{count; capacity; rel}`。

### 8.1 fx::IntensityConfig（0x20）—— 距离/标量/intensity 三处共用

`distance.configs` / `scaler.configs` 的元素，以及 `intensities[i].configs` 的元素，
都是同一个 `fx::IntensityConfig`：

| 偏移 | 类型 | 字段 |
|------|------|------|
| +0x00 | 数组 | `ramp`：`{u32 count; u32 capacity; i64 rel}`（rel 基准 = **本元素**），元素 8 字节 `{f32 time; f32 value}`（寄服是 `{f32 value; f32 time}`，见 §16.4） |
| +0x10 | 数组 | `flags`：`{u32 count; u32 capacity; i64 rel}`（rel 基准 = **本元素**），元素 u32 |

`flags` 的元素类型是 `fx::IntensityMultiplierType`。exe 里**没有**该枚举的成员名字符串
（只有 RTTI 名），实测取值为位掩码组合（`2/4/8/16/…`，如 19 = 1+2+16、23 = 1+2+4+16），
因此明文里按原样输出整数，不做名字映射。

---

## 9. String

```
+0x00  u32  size       含结尾 NUL 的字节数
+0x04  u32  capacity
+0x08  i64  rel        相对**本字段自身地址**的偏移
```

例如渲染器 `textureName0 @0x000`、`size=50`、`rel=0x210` ⇒ 字符串位于区域 `0x000+0x210`。

---

## 10. ValueGeneratorPrototype（0x10）

```
+0x00  u32  type       PS_VALG_TYPE_*
+0x08  i64  rel        相对**本字段自身地址** → 载荷
```

反编译：`FUN_14070fdc0`。

| type | 载荷 | 布局 |
|------|------|------|
| 0 RANDOM | RandomValueGenerator | `{f32 from; f32 to}` |
| 1 CONSTANT | ConstantValueGenerator | `{f32 value}` |
| 2 RAMP | RampValueGenerator（`FUN_14071d8a0`） | `{u32 count; u32 pad; i64 rel→points; u32 parameterType; u32 samplingType}` |
| 3 CUMULATIVE | CumulativeValueGenerator | `{f32 from; f32 to; …}` |

Ramp 的 points：`count` 个 `{f32 time; f32 value}`，`rel` 基准 = **载荷起点**
（二进制里先 time 后 value，与 XML 的 `<point time= value=>` 对应）。

⚠️ **寄服把点元素的字段顺序反过来了**：`{f32 value; f32 time}`（见 §16）。

---

## 11. VectorGeneratorPrototype（0x10）

```
+0x00  u32  type       PS_VGT_*
+0x04  u32  count      prototypes 数量
+0x08  i64  rel        相对**本字段自身地址** → prototypes（每个 0x10）
```

反编译：`FUN_140710050`（集合）/ `FUN_14071daf0`（单个 prototype）。

每个 prototype：

```
+0x00  u32  type       PS_VGT_*
+0x08  i64  rel        相对 **prototype 自身地址** → 几何数据
```

| type | 几何数据 |
|------|----------|
| 0 BOX | `vec3 corner; vec3 opposite`（24 字节） |
| 1 POINT | `vec3`（12 字节） |
| 2 CYLINDER | `vec3 corner @0x00; f32 maxRadius @0x0C; vec3 basisU @0x10; f32 minRadius @0x1C; vec3 basisV @0x20; vec3 difference @0x2C; f32 scale @0x38`（0x3C） |
| 3 SPHERE | `vec3 center; f32 radius` |
| 4 LINE | `vec3 from; vec3 to` |

---

## 12. ComponentPrototype（0x10）与动作类型

`components` 数组元素：

```
+0x00  u32  type       PS_CT_*
+0x08  i64  rel        相对**元素自身地址** → 动作载荷
```

动作载荷头部同样是 `{u32 type; u32 pad; i64 rel}`，
`type` 为 `PS_CPAT_*`（粒子动作）或 `PS_CSAT_*`（系统动作），
`rel` 指向**该动作的参数结构**（基准 = 载荷自身地址）。

反编译：`FUN_140707d80`（分派）/ `FUN_140716880`（粒子动作）/ `FUN_140717220`（系统动作）。

### 12.1 粒子动作（PS_CPAT）

| 动作 | 参数结构 |
|------|----------|
| DAMPFER | `ValueGen velocityGenerator @0x00; f32 delay @0x10` |
| STREAM | `vec3 point @0x00; f32 delay @0x0C; f32 halfLife @0x10; bool switchCoordinateStyle @0x14` |
| JITTER | `VectorGen velocity @0x00; VectorGen position @0x10; f32 delay @0x20; bool affectPosition @0x24; bool affectVelocity @0x25` |
| FORCE | `ValueGen forceX @0x00; forceY @0x10; forceZ @0x20; f32 delay @0x30` |
| RESIZER | `u32 保留 @0x00; f32 rate @0x04; f32 targetSize @0x08; 保留 @0x0C` |
| ORBITOR | `ValueGen angularVelocity @0x00; vec3 point @0x10; vec3 axis @0x1C; f32 delay @0x28; bool affectPosition @0x2C; bool affectVelocity @0x2D` |
| SCALER | `ValueGen size @0x00; ValueGen scaleX @0x10; f32 delay @0x20` |
| TINT_SHADER | `tint` 数组 @0x00（元素 `{rgba, f32 time @0x10}`，步长 0x14）; f32 delay @0x10; f32 period @0x14; u32 保留 @0x18; bool repeat @0x1C; useVelocity @0x1D; useEmitterAge @0x1E |
| BARRIER_CYLINDER / BARRIER_SPHERE | `String effectName @0x00; vec3 position @0x10; i32 reaction @0x1C; f32 strength @0x20; f32 stopAge @0x24; f32 delay @0x28; f32 radius @0x2C` |
| ALPHA_SETTER | `ramp` 数组 @0x00（元素 `{f32 time, f32 value}`，步长 8）; f32 delay @0x10 |
| MAGNET | `vec3 point @0x00; f32 delay @0x0C; f32 minimalDistance @0x10; f32 strength @0x14` |
| BARRIER_BOX | `String effectName @0x00; vec3 opposite @0x10; vec3 corner @0x1C; f32 strength @0x28; f32 stopAge @0x2C; i32 reaction @0x30; f32 delay @0x34` |

### 12.2 系统动作（PS_CSAT）

`DAMPFER / STREAM / JITTER / FORCE / ORBITOR / BARRIER_CYLINDER / BARRIER_SPHERE /
MAGNET / BARRIER_BOX` 与同名粒子动作**完全共用**同一套结构；其余：

| 动作 | 参数结构 |
|------|----------|
| TRAIL_SPAWNER | `String trailName @0x00; bool queryEdit @0x10` |
| EFFECT_SPAWNER | `ramp 数组 @0x00; String effectName @0x10` |
| BARRIER_PLANE | `String effectName @0x00; vec4 planeEquation @0x10; i32 reaction @0x20; f32 strength @0x24; f32 stopAge @0x28; f32 delay @0x2C; bool useWorldSpace @0x30` |
| CREATOR | `ramp 数组 @0x00; VectorGen initialPosition @0x10; VectorGen initialVelocity @0x20; f32 systemAgeLimitMin @0x30; systemAgeLimitMax @0x34; velocityInheritanceFactor @0x38; u32 minRandomRateBound @0x3C; bool repeated @0x40; useSmoothRate @0x41; useWorldCoordinates @0x42` |

> 「ramp 数组」= `{u32 count; u32 capacity; i64 rel}`（元素 `{f32 time; f32 value}`，步长 8），
> `rel` 基准 = 字段自身地址；26.11PT1 未给 STREAM / MAGNET 前 12 字节登记字段名，按 `point` 输出；
> 各动作结构尾部按 8/16 字节对齐的留白在表里登记为 `pad*`，明文里不出现（恒为 0 时）。

### 12.3 光照 / 贴花组件（PS_CT_LIGHT_SOURCE / PS_CT_DECAL_SOURCE）

这两类组件的载荷**不是** `PS_CPAT/CSAT` 动作，而是各自的联合体，`payload` 头 4 字节是
变体选择子（`kind`，0 = 结构体，其它值 exe 直接报 "Invalid type"）。

光照（反编译：`FUN_14070e990` → `FUN_1401c54b0` → 动画 `FUN_1401c7eb0` / `FUN_1401c8080`）：

```
payload:  +0x00 i32 kind (=0)
          +0x08 i64 rel  → fx::LocalLightSourcePrototype（基准 = 载荷起点）
```

`fx::LocalLightSourcePrototype`（0x88）：

| 偏移 | 类型 | 字段 |
|------|------|------|
| +0x00 | struct | `colorAnimation`（0x20） |
| +0x20 | struct | `radiusAnimation`（0x20） |
| +0x40 | vec4 | color |
| +0x50 | vec3 | localPosition |
| +0x60 | f32 | radius |
| +0x64 | f32 | innerAngle |
| +0x68 | f32 | outerAngle |
| +0x6C | f32 | falloff |
| +0x70 | f32 | specularIntensity |
| +0x74 | f32 | visibleDistance |
| +0x78 | u32 | type（实测 1 / 2） |
| +0x7C | u32 | minQuality |
| +0x84 | bool×3 | animatedColor / animatedRadius / enabled |

动画结构（0x20）：

```
+0x00  f32  duration       （exe 里没有登记字段名；实测为 0.3 / 1 / 7 之类的时长）
+0x04  u32  repeated       （bool 存在 u32 槽里）
+0x08  u32  u32            恒为 0 的保留槽
+0x10  数组 points：{u32 count; u32 capacity; i64 rel}
                           ⚠️ rel 基准 = **本动画结构 +0x10**（数组描述符自身），不是结构起点
```

点的元素形状**两个动画不一样**（按 `time` 单调性实测确认，两服一致）：

| 动画 | 元素 | 明文 |
|------|------|------|
| `colorAnimation` | 0x14 = `{f32 time; vec4 color}` | `<item><value>r g b a</value><time>…</time></item>` |
| `radiusAnimation` | 0x08 = `{f32 time; f32 value}` | `<item><value>v</value><time>…</time></item>` |

贴花（反编译：`FUN_140717b90` → `FUN_1401c5e70`）：

```
payload:  +0x00 i32 kind (=0)
          +0x48 ValueGen alpha
          +0x58 i64 rel → fx::DecalSourcePrototype
结构:     +0x00 u32 technique; +0x04 u32 influence; +0x08 u32 priority; +0x0C f32 alpha;
          +0x10 数组 textures：String[]（rel 基准 = 结构起点）
```

> 26.11PT1 数据里 `PS_CT_LIGHT_SOURCE` 有 553 处、`PS_CT_DECAL_SOURCE` **0 处**；
> 贴花分支按反编译结果实现，但没有实盘数据可交叉验证。

---

## 13. 枚举（顺序 = exe 内字符串表顺序，已与分派代码交叉验证）

| 表 | 取值 |
|----|------|
| PS_PCS | VIEW, SCREENSPACE, WORLD, LOCAL |
| PS_RBT | BLENDED_WATER_SURFACE, DEFORM_WATER_SURFACE, ADDITIVE, BLENDED_UNDERWATER, ADDITIVE_WATER_SURFACE, UNDERWATER_GRADIENT_MAP, BLENDED_GLOW, GRADIENT_MAP, SHIMMER, BLENDED |
| PS_RST | OLDEST, YOUNGEST, DISTANCE |
| PS_RRC | BOTTOM, CORNER, CENTER, CUSTOM |
| PS_RLT | LAMBERT, LIGHTMAPPING_4WAY, LIGHTMAPPING_HL2 |
| PS_PAT | NO_ANIMATION, FRAMES_PLAYBACK, MOTION_VECTORS |
| PS_VGT | BOX, POINT, CYLINDER, SPHERE, LINE |
| PS_VALG_TYPE | RANDOM, CONSTANT, RAMP, CUMULATIVE |
| PS_VALG_RAMP_PARAMETER | SYSTEM_AGE, PARTICLE_AGE, SYSTEM_VELOCITY, PARTICLE_VELOCITY, SYSTEM_ACTIVE_TIME, PARTICLE_INDEX |
| PS_VALG_RAMP_SAMPLING | LOOP, PING_PONG, ONCE |
| PS_CT | PARTICLE_ACTION, LIGHT_SOURCE, DECAL_SOURCE, SYSTEM_ACTION |
| PS_CPAT | DAMPFER, STREAM, JITTER, FORCE, RESIZER, ORBITOR, SCALER, TINT_SHADER, BARRIER_CYLINDER, ALPHA_SETTER, BARRIER_SPHERE, MAGNET, BARRIER_BOX |
| PS_CSAT | DAMPFER, TRAIL_SPAWNER, EFFECT_SPAWNER, STREAM, JITTER, FORCE, BARRIER_PLANE, BARRIER_CYLINDER, ORBITOR, BARRIER_SPHERE, MAGNET, BARRIER_BOX, CREATOR |
| PS_PVVM | INDEPENDENT_FROM_VOLUMETRICS, INVISIBLE_WITH_VOLUMETRICS_ENABLED, VISIBLE_ONLY_WITH_VOLUMETRICS |

---

## 14. 明文（XML）与回写

### 14.1 浏览器里的输出：一个粒子 `.xml` 一份明文

assets.bin 里 `/particles/xxx.xml` 是**目录**，`high` / `low` / `shared` 是三条独立记录
（`EffectPrototype` ×2 + `EffectMetadataPrototype`）。浏览器导出时会把它们**合成一份**
`xxx.xml`，格式对齐游戏自带的粒子明文（参考
`res_unpack/helpers/particles/sfx_fail.xml`）：

```xml
<SignalFlare.xml>
	<high>
		<prototype>
			<systemsCount>	5	</systemsCount>
			<systems>
				<item>
					<renderer> … </renderer>
					<emitter> … </emitter>
					<general> … </general>
					<distance> … </distance>
					<name> … </name>
					<animation> … </animation>
					<componentsCount>	3	</componentsCount>
					<components>
						<item>
							<type>	PS_CT_PARTICLE_ACTION	</type>
							<data>
								<type>	PS_CPAT_TINT_SHADER	</type>
								<data> …动作字段… </data>
							</data>
						</item>
					</components>
					<intensities> … </intensities>
					<scaler> … </scaler>
				</item>
			</systems>
			<maxEmittingDuration>	7.8000	</maxEmittingDuration>
		</prototype>
	</high>
	<low> … 同上 … </low>
	<shared>
		<prototype>
			<intensitiesCount>	6	</intensitiesCount>
			<intensitiesMetadata>
				<item>
					<intensityName> <size>	12	</size><text>	Intensity 0	</text> </intensityName>
					<minIntensity>	0.0000	</minIntensity>
					<maxIntensity>	10.0000	</maxIntensity>
					<defaultIntensity>	1.0000	</defaultIntensity>
				</item>
			</intensitiesMetadata>
		</prototype>
	</shared>
</SignalFlare.xml>
```

格式约定与 `sfx_fail.xml` 一致：制表符缩进、标量夹在 `\t` 之间、浮点固定 4 位小数、
向量空格分隔、点写成 `<value>` 再 `<time>`、生成器 `<type>` + `<data>`、
组件 `<type>` + `<data>`（动作类型再套一层 `<data>`）。

- 该格式由 `fx.format_particle_text({...}, "xxx.xml")` 生成；缺哪个分区就不写哪个
  （实测 1689 个粒子文件里 780 个有 high+low+shared、909 个只有 high+shared）。
- 根节点名 = 粒子文件名（非法 XML 名时退回 `<particle>`）。
- 全量 1689 份合并结果都能被 `ElementTree` 解析。
- **文件树里也只有一个节点**：`/particles/xxx.xml` 这个「只装 high/low/shared 的目录」
  会折叠成一行（类型列显示 `粒子效果 .xml`），点它直接得到合并后的整份明文；
  不再展开出 `high` / `shared` 两行。搜索命中任一分区都定位到这一行。

### 14.2 结构视图（调试用）

`fx.format_effect_text()` 输出带 `at` / `size` / 字段结构属性的单记录视图，
便于对照二进制位置（不出现在导出文件里）：

```xml
<effect maxEmittingDuration="-1.0" systemsCount="1" regionSize="1320">
  <system index="0">
    <renderer>
      <textureName0 at="0x210" size="50">particles/...</textureName0>
      <yawRateRamp type="PS_VALG_TYPE_RAMP" at="0x254">
        <ramp count="8" parameterType="..." samplingType="..." at="0x26C">
          <point time="0.0" value="11.2374"/>
        </ramp>
      </yawRateRamp>
    </renderer>
    <components count="3" at="0x913">
      <component type="PS_CT_PARTICLE_ACTION" action="PS_CPAT_TINT_SHADER"
                 at="0x943" fieldsAt="0x953">
        <tint at="0x973" count="4">
          <point time="0.0" r="1.0" g="1.0" b="0.14" a="0.0"/>
        </tint>
        <delay>0.0</delay>
        <period>1.6</period>
        <repeat>true</repeat>
      </component>
      <component type="PS_CT_LIGHT_SOURCE" kind="0" at="0x2819" fieldsAt="0x2829">
        <colorAnimation at="0x28B1" count="8">
          <duration>7.0</duration>
          <repeated>false</repeated>
          <point time="0.0" value="2.0"/>
        </colorAnimation>
        <color x="20.0" y="6.25" z="0.6" w="1.0"/>
        <localPosition x="0.0" y="0.1" z="0.0"/>
        <radius>1.0</radius>
      </component>
    </components>
    <distance>
      <maxDistance>60.0</maxDistance>
      <configs at="0x13BB" count="2">
        <item>
          <ramp at="0x13FB" count="8">
            <point time="0.0" value="1.0"/>
          </ramp>
          <flags at="0x143B" count="1"><flag>19</flag></flags>
        </item>
      </configs>
    </distance>
  </system>
</effect>
```

- `at` / `size` 等属性用于精确定位（字符串与载荷都在变长池里）。
- 覆盖情况：26.11PT1 全量 2469 条记录里，**结构化字段（含 intensities 每一级配置、
  距离/标量曲线、光照组件、全部动作参数）均已解码**。数据池里剩余约 4.6% 字节
  **没有被任何字段引用**（对象之间的对齐留白、描述符链尾），它们只用于回写保真，
  **明文里不输出**。
- 各结构里恒为 0 的保留/对齐槽在字段表里登记为 `pad*`：解码时标记覆盖但不写进 XML
  （非 0 时才以 hex 属性出现）。
- `fx.encode_region()` 按同一份字段表回写；**未改动时与原始区域逐字节一致**
  （正式服 2469 条 EffectPrototype + 1689 条 EffectMetadataPrototype 全部通过往返校验）。

当前限制（都不影响阅读）：

- 字符串新值不能长于原 `size-1`（不做自动扩容/重排）。
- `fx::IntensityMultiplierType`（`flags` 元素）在 exe 里没有成员名字符串，只能输出整数位掩码。
- 光照动画首字段没有登记名（本文按 `duration` 输出）；`LocalLightSource` 的 `@0x78 type`
  取值 1/2 的含义未还原。
- 贴花组件在 26.11PT1 数据里 0 处，未做实盘验证。

---

## 15. EffectMetadataPrototype（粒子 `/xxx.xml/shared`）

粒子路径下的 `shared` 部分不是 EffectPrototype，而是独立的
`EffectMetadataPrototype`（magic `0xDFC8F8E0`，blob 7）：它给出该效果
**强度通道（intensities）的名称与取值范围**。

反编译：`FUN_1406daa00`（类型 unpack 入口）→ `FUN_1406e18a0`（数组校验）→
`FUN_1406e6850`（逐条）→ `FUN_1406f3d30`（单条 `intensitiesMetadata`）。

记录（16 字节）：

```
+0x00  u32  count
+0x04  u32  pad
+0x08  i64  rel          相对**本记录起点** → 元素数组
+0x10  下一条记录
```

元素（0x20 字节）：

```
+0x00  String intensityName        （size/capacity/rel，rel 基准 = 字段自身）
+0x10  f32    minIntensity
+0x14  f32    maxIntensity
+0x18  f32    defaultIntensity
+0x1C  u32    未具名（26.10 / 26.11 数据里恒为 0，原样保留）
```

区域 = 元素数组 + 紧随其后的字符串池，长度按本记录实际内容算出。
实测 1689 条记录的 `count` 恒为 6（`Intensity 0`…`Intensity 5`），
少数效果用 `Size` / `R` / `G` / `B` / `A` 之类的自定义通道名。

明文（`/particles/SignalFlare.xml/shared` 为 `/shared`，`high`/`low` 为效果本体）：

```xml
<effectMetadata name="/particles/Ray_DotLine_APR24_crossed.xml/shared"
                count="6" regionSize="256">
  <intensity name="Scale Tiling" min="0.0" max="10.0" default="1.52" at="0xC0"/>
  <intensity name="ColorRGB"    min="0.0" max="12.0" default="0.4"  at="0xCD"/>
  ...
</effectMetadata>
```

对应 API：`fx.decode_metadata_data()` / `fx.encode_metadata_region()` /
`fx.format_metadata_text()`；`fx.format_effect_text()` 会按 `_type` 自动分派。

配合第 3 章的 `intensities`（每通道的强度曲线）与本章的通道名/范围，
`high`/`low` 与 `shared` 三部分现在都能各自解析成明文。

---

## 16. 寄服（Wargaming）布局差异

寄服 `WorldOfWarships64.exe`（build 13357625）的 `fx::PSPrototype` 只有
**0x1C8** 字节（莱服 0x210），且若干子结构与莱服不同。`fx.py` 用布局档案
（`LAYOUTS["Lesta"]` / `LAYOUTS["Wargaming"]`，由 `current_layout()` 按当前
线程的 `types.get_wows_type()` 选取）承载这些差异；解码结果带
`"_layout"` 键，`encode_region()` 按它回写。

反编译依据（同一 Ghidra 工程，脚本 `FxWgBfs.java` / `FxWgDecomp.java`）：

| 函数 | 作用 |
|------|------|
| `FUN_1408312f0` | `fx::PSPrototype`（0x1C8） |
| `FUN_140834bd0` | `fx::RendererPrototype`（0xA0） |
| `FUN_140835bc0` | `fx::EmitterPrototype`（0x90，与莱服**完全一致**） |
| `FUN_140836220` | `fx::AnimationPrototype`（0x40） |
| `FUN_1408367c0` | `fx::GeneralPrototype`（0x18） |
| `FUN_140836b50` | `fx::DistancePrototype`（0x10，与莱服一致） |
| `FUN_140836fc0` / `FUN_140841c10` / `FUN_140841990` | intensities 通道 / configs / `IntensityConfig`（与莱服一致） |
| `FUN_1408371d0` | `ComponentPrototype` 分派（PS_CT 数值与莱服相同） |
| `FUN_140842fd0` / `FUN_140843970` | 粒子动作 / 系统动作分派（type 数值见下） |
| `FUN_14083f590` / `FUN_140852710` | 光照组件载荷 / `LocalLightSourcePrototype`（0x70） |
| `FUN_140840d60` | `fx::RampPrototype`（`{u32 count; u32 capacity; i64 rel}` + 8 字节点） |
| `FUN_1408414a0` | `ValueGeneratorPrototype` 分派 |

### 16.1 PSPrototype 偏移对照

| 子结构 | 莱服 | 寄服 |
|--------|------|------|
| renderer | 0x000（0xD0） | 0x000（0xA0） |
| emitter | 0x0D0（0x90） | 0x0A0（0x90） |
| animation | 0x160（0x40） | 0x130（0x40） |
| general | 0x1A0（0x20） | 0x170（0x18） |
| distance | 0x1C0（0x10） | 0x188（0x10） |
| scaler | 0x1D0（0x10） | **不存在** |
| name | 0x1E0 | 0x198 |
| intensities | 0x1F0 | 0x1A8 |
| componentsCount / rel | 0x200 / 0x208 | 0x1B8 / 0x1C0 |

### 16.2 渲染器（0xA0）

寄服**没有** `particleMeshPath`，也没有按轴拆分的自旋/朝向标量
（`spinRateYaw/Pitch/Roll`、`orientation*`）；`customCenterOffset` 是 **Vector2**
（0x3C），`yawRateRamp` 在 0x20 且是**裸 `RampPrototype`**（不再套
`<type>/<data>`）。其余偏移见 `fx.WG_RENDERER_FIELDS`；0x64 在寄服未登记，
按 4 字节保留槽处理。

### 16.3 其余子结构

* `general`（0x18）：`capacity` / `maxInstancesCount` / `maxParticleAge` /
  `cameraAttachOffset` / `coordinateStyle` / `reflectionVisible` / `prewarm`，
  没有 `volumetricsVisibilityMode` 与水体剔除等开关。
* `animation`：`frameRateRamp`（0x00）同样是**裸 ramp**。
* `LocalLightSourcePrototype` 由 0x88 缩到 **0x70**：
  `colorAnimation@0` / `radiusAnimation@0x20` / `color@0x40` /
  `localPosition@0x50` / `radius@0x60` / （0x64 未登记，4 字节保留）/
  `animatedColor@0x68` / `animatedRadius@0x69`。寄服没有
  `innerAngle/outerAngle/falloff/specularIntensity/visibleDistance/type/minQuality`。
  两个动画的点元素形状与莱服一致（见 §12.3）。
* `PS_CT_DECAL_SOURCE`：结构未还原，载荷整块按原字节保留（不解析、不输出）。
  实测寄服 76,000+ 个组件里贴花数量为 **0**，所以没有实际损失。

### 16.4 点元素顺序反了

`RampPrototype`（以及 ValueGen 的 RAMP 载荷点、`IntensityConfig.ramp`）里，莱服是
`{f32 time; f32 value}`，寄服是 **`{f32 value; f32 time}`**。
判定方法：同一条曲线内 `time` 必须单调不减 —— 寄服 25,825 条 ramp、
2,406 条 `frameRateRamp`、21,008 条 `IntensityConfig.ramp` 在「第二个分量」上
100% 单调，在第一个分量上则大量不单调；莱服正好相反。
`_Layout.ramp_value_first` 记录这个差异。

例外（**两服一致，都是 time 在前**）：

* tint 点（`color@0`，`time@0x10`）；
* 光照 `colorAnimation`（`{time; vec4 color}`）与 `radiusAnimation`（`{time; value}`）。

### 16.5 枚举数值

`PS_CT`、`PS_VGT`、`PS_VALG_TYPE`（0/1/2 = LINEAR/CONSTANT/RAMP）数值两服一致；
动作枚举**不一致**（寄服 `WG_PS_CPAT` / `WG_PS_CSAT`，数值取自分派分支）：

| PS_CPAT | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 寄服 | DAMPFER | STREAM | JITTER | FORCE | RESIZER | ORBITOR | SCALER | TINT_SHADER | BARRIER_CYLINDER | ALPHA_SETTER | BARRIER_SPHERE | MAGNET | **VELOCITY_FIELD** | BARRIER_BOX |

| PS_CSAT | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 寄服 | DAMPFER | TRAIL_SPAWNER | STREAM | JITTER | FORCE | BARRIER_PLANE | BARRIER_CYLINDER | ORBITOR | BARRIER_SPHERE | MAGNET | **VELOCITY_FIELD** | BARRIER_BOX | CREATOR |

寄服独有的动作载荷：

* `PS_CPAT_VELOCITY_FIELD`（0x38）：`topLeftFront@0` / `bottomRightBack@0xC` /
  `stopAge@0x18` / `delay@0x1C` / `velocityScale@0x20` / `influence@0x24` /
  `fieldSourceName@0x28`（String）。
* `PS_CSAT_TRAIL_SPAWNER`（0x20）：`trailRamp@0`（裸 ramp）/ `trailName@0x10`
  （String，内容是 `particles/xxx.xml/high` 这类引用）。
* 寄服 `PS_CPAT_RESIZER` 是 `{f32 delay; f32 rate; f32 targetSize}`（莱服首字段未具名）。

### 16.6 字符串

寄服的空字符串是 `size=2` 且载荷为 `\x00\x00`（莱服是 `size=1`）。
`_decode_string()` 现在按「首个 NUL 之前必须是可打印 ASCII，之后必须全是 NUL」
判定，两种写法都能解、都能原样回写。

### 16.7 验证结果

| 项目 | 结果 |
|------|------|
| EffectPrototype 解码 | 3623 / 3623 |
| EffectMetadata 解码 | 2405 / 2405 |
| 往返逐字节一致 | 3623 / 3623 + 2405 / 2405 |
| 合并明文 XML 可解析 | 2405 / 2405 个 group（high+low+shared） |
| 系统结构内未解码字节 | 0 / 10,133,232 |
| 数据池未解码字节 | 593,696 / 29,224,670（2.03%，全是 4 字节对齐填充/空闲区） |
| 莱服回归 | 2469 / 2469 + 1689 / 1689 不变（raw 4.62% → 4.45%，光照颜色曲线补齐） |

覆盖的组件：`PS_CT_PARTICLE_ACTION` 71,907、`PS_CT_LIGHT_SOURCE` 1,008、
`PS_CT_SYSTEM_ACTION` 5,312。
