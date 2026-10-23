"""EffectPrototype（粒子效果）二进制 ⇄ 可读 XML。

本模块为 assets.bin 浏览器的「明文格式 / 导出明文」提供粒子效果支持：
``decoders.decode_effect`` 调用 :func:`decode_effect_data` 得到结构化 dict，
:func:`format_particle_text` 再把同一粒子文件的 ``high`` / ``low`` / ``shared``
合成一份与游戏自带粒子 XML（``helpers/particles/sfx_fail.xml``）同版式的明文；
:func:`encode_region` 可把解码结果写回区域字节（未改动时与原始字节完全一致）。
:func:`format_effect_text` 是带偏移的**结构视图**，仅用于调试对照。

粒子的 ``/particles/xxx.xml/shared`` 部分（``EffectMetadataPrototype``，
强度通道元数据）同样可解码：:func:`decode_metadata_data` /
:func:`encode_metadata_region`。

格式依据
--------
结构来自 Ghidra 反编译（工程 ``Uncode_Korabli``）：莱服 26.11PT1 的
``Korabli64.exe``（系统结构 0x210）与寄服 ``WorldOfWarships64.exe``
build 13357625（系统结构 0x1C8）。两套布局由 :data:`LAYOUTS` 里的布局档案
描述，解码时按当前线程的 ``types.get_wows_type()`` 自动选取
（:func:`current_layout`）；寄服差异见 ``docs/korabli-particles-effect-format.md`` §16。

下表为莱服函数：

===========================  ==============================================
函数                         作用
===========================  ==============================================
``FUN_1408e3940``            assets.bin 原型库加载（类型表 / 校验和）
``FUN_1406d9cc0``            EffectPrototype 类型 unpack 入口
``FUN_1406e1420``            校验 ``{u32 count; u32 pad; i64 rel}`` 数组
``FUN_1406e8da0``            EffectPrototype 单条记录
``FUN_1406f3180``            ``fx::PSPrototype``（0x210）
``FUN_140703800``            ``fx::RendererPrototype``（0xD0）
``FUN_140704d30``            ``fx::EmitterPrototype``（0x90）
``FUN_1407053a0``            ``fx::AnimationPrototype``（0x40）
``FUN_140703080``            ``fx::GeneralPrototype``（0x20）
``FUN_1407059f0``            ``fx::DistancePrototype`` / ``ScalerPrototype``（0x10）
``FUN_14070fdc0``            ``ValueGeneratorPrototype`` 分派
``FUN_14071d8a0``            ``RampValueGenerator``（points / parameterType / samplingType）
``FUN_140710050``            ``VectorGeneratorPrototype`` 集合（count + prototypes）
``FUN_14071daf0``            ``VectorGeneratorPrototype`` 分派（box/point/cylinder/sphere/line）
``FUN_140707d80``            ``ComponentPrototype`` 分派（particleAction/light/decal/systemAction）
``FUN_140716880``            ``PS_CPAT_*`` 粒子动作载荷校验（各动作字段偏移）
``FUN_140717220``            ``PS_CSAT_*`` 系统动作载荷校验（复用同名结构）
``FUN_1407120e0``            ``fx::IntensityConfig``（0x20：ramp 曲线 + flags）
``FUN_14070d920``            ``fx::IntensityPrototype``（0x10：configs 数组）
``FUN_14070e990``            ``PS_CT_LIGHT_SOURCE`` 载荷（→ ``FUN_1401c54b0``）
``FUN_1401c54b0``            ``fx::LocalLightSourcePrototype``（0x88）
``FUN_1401c7eb0``            ``LocalLight`` 的 colorAnimation / radiusAnimation
``FUN_140717b90``            ``PS_CT_DECAL_SOURCE`` 载荷（→ ``FUN_1401c5e70``）
``FUN_1401c5e70``            ``fx::DecalSourcePrototype``（technique/influence/…/textures）
``FUN_1406daa00``            EffectMetadataPrototype 类型 unpack 入口
``FUN_1406e18a0``            EffectMetadata 记录 ``{u32 count; i64 rel}`` 数组校验
``FUN_1406e6850``            逐条 ``intensitiesMetadata``
``FUN_1406f3d30``            ``intensitiesMetadata`` 单条（name/min/max/default）
===========================  ==============================================

关键约定（2469 条正式服记录实测校验）：

* 记录（16 字节）::

      +0x00  f32  maxEmittingDuration
      +0x04  u32  systemsCount
      +0x08  i64  systems（**相对指针，基准 = 本记录起点**）
      +0x10  下一条记录

* ``systems`` 区域 = ``systemsCount`` 个 ``PSPrototype``（莱服每 0x210 字节，
  寄服每 0x1C8 字节），紧跟其后的是变长数据池（字符串、ramp 点、action 载荷……）。
* 字符串 = ``{u32 size（含结尾 NUL）; u32 capacity; i64 rel}``，
  ``rel`` 基准是**该字段自身地址**。
* 生成器 / 组件 = ``{u32 type; u32 count; i64 rel}``，``rel`` 基准为该字段自身地址
  （components 数组例外：基准是系统结构起点，已按反编译结果固定）。
* 枚举顺序取自 exe 内 ``PS_*`` 字符串表，并与分派代码交叉验证
  （``PS_VALG_TYPE`` = RANDOM/CONSTANT/RAMP/CUMULATIVE 与 ``FUN_14070fdc0`` 一致）。
* 数组统一是 ``{u32 count; u32 capacity; i64 rel}``（16 字节）；唯一例外是
  ``DistancePrototype`` / ``ScalerPrototype`` 的 ``configs``（紧凑形式
  ``{u32 count; i64 rel}``，rel 在 +0x04）。
* 曲线点元素顺序**两服不同**：莱服 ``{f32 time; f32 value}``，
  寄服 ``{f32 value; f32 time}``（``_Layout.ramp_value_first``）。
* 所有结构化字段都已解码；数据池里没有被任何字段引用的对齐/空闲字节
  收进 ``raw`` 列表用于无损回写，但**不写进明文**（对阅读没有意义）。
* 寄服的 ``PS_CT_DECAL_SOURCE`` 结构未还原，载荷原样保留（实测寄服数据里
  没有贴花组件，所以不影响可读性）。
"""

from __future__ import annotations

import struct
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# ── 布局常量 ──────────────────────────────────────────────────────────────

#: 单条系统结构（fx::PSPrototype）序列化长度
SYSTEM_SIZE = 0x210
#: EffectPrototype 记录长度
RECORD_SIZE = 0x10
#: 数据块头长度（`{u64 count; u64 header_size}`）
BLOB_HEADER = 0x10

#: 枚举表（顺序 = exe 内字符串表顺序，已与数据交叉验证）
ENUMS: Dict[str, Tuple[str, ...]] = {
    "PS_PCS": ("PS_PCS_VIEW", "PS_PCS_SCREENSPACE", "PS_PCS_WORLD", "PS_PCS_LOCAL"),
    "PS_RBT": (
        "PS_RBT_BLENDED_WATER_SURFACE", "PS_RBT_DEFORM_WATER_SURFACE", "PS_RBT_ADDITIVE",
        "PS_RBT_BLENDED_UNDERWATER", "PS_RBT_ADDITIVE_WATER_SURFACE",
        "PS_RBT_UNDERWATER_GRADIENT_MAP", "PS_RBT_BLENDED_GLOW", "PS_RBT_GRADIENT_MAP",
        "PS_RBT_SHIMMER", "PS_RBT_BLENDED",
    ),
    "PS_RST": ("PS_RST_OLDEST", "PS_RST_YOUNGEST", "PS_RST_DISTANCE"),
    "PS_RRC": ("PS_RRC_BOTTOM", "PS_RRC_CORNER", "PS_RRC_CENTER", "PS_RRC_CUSTOM"),
    "PS_RLT": ("PS_RLT_LAMBERT", "PS_RLT_LIGHTMAPPING_4WAY", "PS_RLT_LIGHTMAPPING_HL2"),
    "PS_PAT": ("PS_PAT_NO_ANIMATION", "PS_PAT_FRAMES_PLAYBACK", "PS_PAT_MOTION_VECTORS"),
    "PS_VALG_TYPE": (
        "PS_VALG_TYPE_RANDOM", "PS_VALG_TYPE_CONSTANT", "PS_VALG_TYPE_RAMP",
        "PS_VALG_TYPE_CUMULATIVE",
    ),
    "PS_VALG_RAMP_PARAMETER": (
        "PS_VALG_RAMP_PARAMETER_SYSTEM_AGE", "PS_VALG_RAMP_PARAMETER_PARTICLE_AGE",
        "PS_VALG_RAMP_PARAMETER_SYSTEM_VELOCITY", "PS_VALG_RAMP_PARAMETER_PARTICLE_VELOCITY",
        "PS_VALG_RAMP_PARAMETER_SYSTEM_ACTIVE_TIME", "PS_VALG_RAMP_PARAMETER_PARTICLE_INDEX",
    ),
    "PS_VALG_RAMP_SAMPLING": (
        "PS_VALG_RAMP_SAMPLING_LOOP", "PS_VALG_RAMP_SAMPLING_PING_PONG",
        "PS_VALG_RAMP_SAMPLING_ONCE",
    ),
    "PS_VGT": (
        "PS_VGT_BOX", "PS_VGT_POINT", "PS_VGT_CYLINDER", "PS_VGT_SPHERE", "PS_VGT_LINE",
    ),
    "PS_CT": ("PS_CT_PARTICLE_ACTION", "PS_CT_LIGHT_SOURCE", "PS_CT_DECAL_SOURCE",
              "PS_CT_SYSTEM_ACTION"),
    "PS_CPAT": (
        "PS_CPAT_DAMPFER", "PS_CPAT_STREAM", "PS_CPAT_JITTER", "PS_CPAT_FORCE",
        "PS_CPAT_RESIZER", "PS_CPAT_ORBITOR", "PS_CPAT_SCALER", "PS_CPAT_TINT_SHADER",
        "PS_CPAT_BARRIER_CYLINDER", "PS_CPAT_ALPHA_SETTER", "PS_CPAT_BARRIER_SPHERE",
        "PS_CPAT_MAGNET", "PS_CPAT_BARRIER_BOX",
    ),
    "PS_CSAT": (
        "PS_CSAT_DAMPFER", "PS_CSAT_TRAIL_SPAWNER", "PS_CSAT_EFFECT_SPAWNER",
        "PS_CSAT_STREAM", "PS_CSAT_JITTER", "PS_CSAT_FORCE", "PS_CSAT_BARRIER_PLANE",
        "PS_CSAT_BARRIER_CYLINDER", "PS_CSAT_ORBITOR", "PS_CSAT_BARRIER_SPHERE",
        "PS_CSAT_MAGNET", "PS_CSAT_BARRIER_BOX", "PS_CSAT_CREATOR",
    ),
    "PS_PVVM": (
        "PS_PVVM_INDEPENDENT_FROM_VOLUMETRICS",
        "PS_PVVM_INVISIBLE_WITH_VOLUMETRICS_ENABLED",
        "PS_PVVM_VISIBLE_ONLY_WITH_VOLUMETRICS",
    ),
    "PS_CLT": ("PS_CLT_LOCAL",),
    # ── 寄服（WG）独有的枚举顺序：由 WorldOfWarships64.exe 的分派分支读出 ──
    "WG_PS_CPAT": (
        "PS_CPAT_DAMPFER", "PS_CPAT_STREAM", "PS_CPAT_JITTER", "PS_CPAT_FORCE",
        "PS_CPAT_RESIZER", "PS_CPAT_ORBITOR", "PS_CPAT_SCALER", "PS_CPAT_TINT_SHADER",
        "PS_CPAT_BARRIER_CYLINDER", "PS_CPAT_ALPHA_SETTER", "PS_CPAT_BARRIER_SPHERE",
        "PS_CPAT_MAGNET", "PS_CPAT_VELOCITY_FIELD", "PS_CPAT_BARRIER_BOX",
    ),
    "WG_PS_CSAT": (
        "PS_CSAT_DAMPFER", "PS_CSAT_TRAIL_SPAWNER", "PS_CSAT_STREAM", "PS_CSAT_JITTER",
        "PS_CSAT_FORCE", "PS_CSAT_BARRIER_PLANE", "PS_CSAT_BARRIER_CYLINDER",
        "PS_CSAT_ORBITOR", "PS_CSAT_BARRIER_SPHERE", "PS_CSAT_MAGNET",
        "PS_CSAT_VELOCITY_FIELD", "PS_CSAT_BARRIER_BOX", "PS_CSAT_CREATOR",
    ),
    "WG_PS_VALG_TYPE": (
        "PS_VALG_TYPE_LINEAR", "PS_VALG_TYPE_CONSTANT", "PS_VALG_TYPE_RAMP",
    ),
}


class FxFormatError(ValueError):
    """粒子效果数据不符合预期结构。"""


# ── 字段表（偏移来自反编译）────────────────────────────────────────────────

#: kind: f32 / i32 / u32 / bool / vec3 / string / value / vector / enum:<表>
RENDERER_FIELDS: Tuple[Tuple[str, int, str], ...] = (
    ("textureName0", 0x000, "string"),
    ("textureName1", 0x010, "string"),
    ("particleMeshPath", 0x020, "string"),
    ("yawRateRamp", 0x030, "value"),
    ("explicitOrientation", 0x040, "vec3"),
    ("customCenterOffset", 0x04C, "vec3"),
    ("spinRateYaw", 0x054, "f32"),
    ("spinRatePitch", 0x058, "f32"),
    ("spinRateRoll", 0x05C, "f32"),
    ("spinRateYawSpread", 0x060, "f32"),
    ("spinRatePitchSpread", 0x064, "f32"),
    ("spinRateRollSpread", 0x068, "f32"),
    ("lightingShineness", 0x06C, "f32"),
    ("orientationYawSpread", 0x070, "f32"),
    ("orientationPitchSpread", 0x074, "f32"),
    ("orientationRollSpread", 0x078, "f32"),
    ("lightingAmbient", 0x07C, "f32"),
    ("orientationYaw", 0x080, "f32"),
    ("orientationPitch", 0x084, "f32"),
    ("orientationRoll", 0x088, "f32"),
    ("hideStartCos", 0x08C, "f32"),
    ("scaleX", 0x090, "f32"),
    ("lightingDiffuse", 0x094, "f32"),
    ("lightingTransmission", 0x098, "f32"),
    ("lightWrapAmount", 0x09C, "f32"),
    ("shadowsStrength", 0x0A0, "f32"),
    ("opacityMultiplier", 0x0A4, "f32"),
    ("hideSpeed", 0x0A8, "f32"),
    ("softParticleDepthScale", 0x0AC, "f32"),
    ("rotationCenter", 0x0B0, "enum:PS_RRC"),
    ("lightingType", 0x0B4, "enum:PS_RLT"),
    ("blendType", 0x0B8, "enum:PS_RBT"),
    ("sortType", 0x0BC, "enum:PS_RST"),
    ("tilingU", 0x0C0, "f32"),
    ("tilingV", 0x0C4, "f32"),
    ("explicitOrientationLocal", 0x0C8, "bool"),
    ("billboard", 0x0C9, "bool"),
    ("velocityOriented", 0x0CA, "bool"),
    ("background", 0x0CB, "bool"),
    ("flipTexcoordU", 0x0CC, "bool"),
    ("flipTexcoordV", 0x0CD, "bool"),
    ("_padRenderer", 0x0CE, "pad2"),
)

EMITTER_GENERATORS: Tuple[Tuple[str, int, str], ...] = (
    ("rateGenerator", 0x000, "value"),
    ("initialPositionGenerator", 0x010, "vector"),
    ("initialVelocityGenerator", 0x020, "vector"),
    ("sizeGenerator", 0x030, "value"),
    ("ageScaleGenerator", 0x040, "value"),
    ("ageScaleAuxGenerator", 0x050, "value"),
    ("delayGenerator", 0x060, "value"),
    ("sleepPeriodGenerator", 0x070, "value"),
)

EMITTER_FIELDS: Tuple[Tuple[str, int, str], ...] = (
    ("activePeriod", 0x080, "f32"),
    ("inheritVelocityFactor", 0x084, "f32"),
    ("particleDistributionStrength", 0x088, "f32"),
    ("snapToSeaLevel", 0x08C, "bool"),
    ("_padEmitter", 0x08D, "pad3"),
)

ANIMATION_FIELDS: Tuple[Tuple[str, int, str], ...] = (
    ("frameRateRamp", 0x000, "value"),
    ("motionVectorsTexture", 0x010, "string"),
    ("framesPerY", 0x020, "i32"),
    ("framesPerX", 0x024, "i32"),
    ("framesRangeBegin", 0x028, "i32"),
    ("framesRangeEnd", 0x02C, "i32"),
    ("animationPeriod", 0x030, "f32"),
    ("motionVectorsDistortion", 0x034, "f32"),
    ("animationType", 0x038, "enum:PS_PAT"),
    ("randomFrameOnly", 0x03C, "bool"),
    ("useEmissionAlphaFromMV", 0x03D, "bool"),
    ("_padAnimation", 0x03E, "pad2"),
)

GENERAL_FIELDS: Tuple[Tuple[str, int, str], ...] = (
    ("capacity", 0x00, "i32"),
    ("maxInstancesCount", 0x04, "i32"),
    ("maxParticleAge", 0x08, "f32"),
    ("cameraAttachOffset", 0x0C, "f32"),
    ("coordinateStyle", 0x10, "enum:PS_PCS"),
    ("volumetricsVisibilityMode", 0x14, "enum:PS_PVVM"),
    ("shadowVisible", 0x18, "bool"),
    ("reflectionVisible", 0x19, "bool"),
    ("reducedUpdateRateEnabled", 0x1A, "bool"),
    ("useWaterCulling", 0x1B, "bool"),
    ("complexIntegrationEnabled", 0x1C, "bool"),
    ("prewarm", 0x1D, "bool"),
    ("_padGeneral", 0x1E, "pad2"),
)

#: Distance / Scaler 共用：maxDistance + configs 数组
DISTANCE_FIELDS: Tuple[Tuple[str, int, str], ...] = (
    ("maxDistance", 0x00, "f32"),
)

# ── 粒子动作 / 系统动作载荷 ───────────────────────────────────────────────
#
# 载荷布局来自 ``FUN_140716880``（PS_CPAT 分派）与 ``FUN_140717220``
# （PS_CSAT 分派）调用的各校验函数；同名结构在两者间完全共用。
#
# 注意：
# * ``PS_CPAT_STREAM`` / ``PS_MAGNET`` 前 12 字节是未在校验函数里登记名字的
#   vec3（实测为粒子参考点 / 磁吸点），按 ``point`` 输出。
# * ``PS_CPAT_RESIZER`` 只有 rate / targetSize 两个具名字段，首 4 字节与
#   0x0C 之后不属于本结构，保留在 raw 里。

_ACT_DAMPFER: Tuple[Tuple[str, int, str], ...] = (
    ("velocityGenerator", 0x00, "value"),
    ("delay", 0x10, "f32"),
    ("_padDampfer", 0x14, "pad4"),
)

_ACT_STREAM: Tuple[Tuple[str, int, str], ...] = (
    ("point", 0x00, "vec3"),
    ("delay", 0x0C, "f32"),
    ("halfLife", 0x10, "f32"),
    ("switchCoordinateStyle", 0x14, "bool"),
    ("_padStream", 0x15, "pad3"),
)

_ACT_JITTER: Tuple[Tuple[str, int, str], ...] = (
    ("velocityGenerator", 0x00, "vector"),
    ("positionGenerator", 0x10, "vector"),
    ("delay", 0x20, "f32"),
    ("affectPosition", 0x24, "bool"),
    ("affectVelocity", 0x25, "bool"),
    ("_padJitter", 0x26, "pad2"),
)

_ACT_FORCE: Tuple[Tuple[str, int, str], ...] = (
    ("forceXGenerator", 0x00, "value"),
    ("forceYGenerator", 0x10, "value"),
    ("forceZGenerator", 0x20, "value"),
    ("delay", 0x30, "f32"),
    ("_padForce", 0x34, "pad4"),
)

_ACT_RESIZER: Tuple[Tuple[str, int, str], ...] = (
    ("_padResizerHead", 0x00, "pad4"),
    ("rate", 0x04, "f32"),
    ("targetSize", 0x08, "f32"),
    ("_padResizer", 0x0C, "pad4"),
)

_ACT_ORBITOR: Tuple[Tuple[str, int, str], ...] = (
    ("angularVelocityGenerator", 0x00, "value"),
    ("point", 0x10, "vec3"),
    ("axis", 0x1C, "vec3"),
    ("delay", 0x28, "f32"),
    ("affectPosition", 0x2C, "bool"),
    ("affectVelocity", 0x2D, "bool"),
    ("_padOrbitor", 0x2E, "pad2"),
)

_ACT_SCALER: Tuple[Tuple[str, int, str], ...] = (
    ("sizeGenerator", 0x00, "value"),
    ("scaleXGenerator", 0x10, "value"),
    ("delay", 0x20, "f32"),
    ("_padScaler", 0x24, "pad4"),
)

_ACT_TINT: Tuple[Tuple[str, int, str], ...] = (
    ("tint", 0x00, "tintpoints"),
    ("delay", 0x10, "f32"),
    ("period", 0x14, "f32"),
    ("_padTint", 0x18, "pad4"),
    ("repeat", 0x1C, "bool"),
    ("useVelocity", 0x1D, "bool"),
    ("useEmitterAge", 0x1E, "bool"),
    ("_padTintTail", 0x1F, "pad1"),
)

_ACT_ALPHA_SETTER: Tuple[Tuple[str, int, str], ...] = (
    ("ramp", 0x00, "ramp"),
    ("delay", 0x10, "f32"),
    ("_padAlpha", 0x14, "pad4"),
)

_ACT_MAGNET: Tuple[Tuple[str, int, str], ...] = (
    ("point", 0x00, "vec3"),
    ("delay", 0x0C, "f32"),
    ("minimalDistance", 0x10, "f32"),
    ("strength", 0x14, "f32"),
)

_ACT_BARRIER_BOX: Tuple[Tuple[str, int, str], ...] = (
    ("effectName", 0x00, "string"),
    ("opposite", 0x10, "vec3"),
    ("corner", 0x1C, "vec3"),
    ("strength", 0x28, "f32"),
    ("stopAge", 0x2C, "f32"),
    ("reaction", 0x30, "i32"),
    ("delay", 0x34, "f32"),
)

_ACT_BARRIER_SPHERE: Tuple[Tuple[str, int, str], ...] = (
    ("effectName", 0x00, "string"),
    ("position", 0x10, "vec3"),
    ("reaction", 0x1C, "i32"),
    ("strength", 0x20, "f32"),
    ("stopAge", 0x24, "f32"),
    ("delay", 0x28, "f32"),
    ("radius", 0x2C, "f32"),
)

_ACT_TRAIL_SPAWNER: Tuple[Tuple[str, int, str], ...] = (
    ("trailName", 0x00, "string"),
    ("queryEdit", 0x10, "bool"),
)

_ACT_EFFECT_SPAWNER: Tuple[Tuple[str, int, str], ...] = (
    ("spawnRamp", 0x00, "ramp"),
    ("effectName", 0x10, "string"),
)

_ACT_BARRIER_PLANE: Tuple[Tuple[str, int, str], ...] = (
    ("effectName", 0x00, "string"),
    ("planeEquation", 0x10, "vec4"),
    ("reaction", 0x20, "i32"),
    ("strength", 0x24, "f32"),
    ("stopAge", 0x28, "f32"),
    ("delay", 0x2C, "f32"),
    ("useWorldSpace", 0x30, "bool"),
)

_ACT_CREATOR: Tuple[Tuple[str, int, str], ...] = (
    ("rateRamp", 0x00, "ramp"),
    ("initialPositionGenerator", 0x10, "vector"),
    ("initialVelocityGenerator", 0x20, "vector"),
    ("systemAgeLimitMin", 0x30, "f32"),
    ("systemAgeLimitMax", 0x34, "f32"),
    ("velocityInheritanceFactor", 0x38, "f32"),
    ("minRandomRateBound", 0x3C, "u32"),
    ("repeated", 0x40, "bool"),
    ("useSmoothRate", 0x41, "bool"),
    ("useWorldCoordinates", 0x42, "bool"),
)

#: 动作名（枚举全名）→ 载荷字段表
ACTION_FIELDS: Dict[str, Tuple[Tuple[str, int, str], ...]] = {
    "PS_CPAT_DAMPFER": _ACT_DAMPFER,
    "PS_CPAT_STREAM": _ACT_STREAM,
    "PS_CPAT_JITTER": _ACT_JITTER,
    "PS_CPAT_FORCE": _ACT_FORCE,
    "PS_CPAT_RESIZER": _ACT_RESIZER,
    "PS_CPAT_ORBITOR": _ACT_ORBITOR,
    "PS_CPAT_SCALER": _ACT_SCALER,
    "PS_CPAT_TINT_SHADER": _ACT_TINT,
    "PS_CPAT_ALPHA_SETTER": _ACT_ALPHA_SETTER,
    "PS_CPAT_MAGNET": _ACT_MAGNET,
    "PS_CPAT_BARRIER_BOX": _ACT_BARRIER_BOX,
    "PS_CPAT_BARRIER_SPHERE": _ACT_BARRIER_SPHERE,
    "PS_CPAT_BARRIER_CYLINDER": _ACT_BARRIER_SPHERE,
    "PS_CSAT_DAMPFER": _ACT_DAMPFER,
    "PS_CSAT_STREAM": _ACT_STREAM,
    "PS_CSAT_JITTER": _ACT_JITTER,
    "PS_CSAT_FORCE": _ACT_FORCE,
    "PS_CSAT_ORBITOR": _ACT_ORBITOR,
    "PS_CSAT_MAGNET": _ACT_MAGNET,
    "PS_CSAT_BARRIER_BOX": _ACT_BARRIER_BOX,
    "PS_CSAT_BARRIER_SPHERE": _ACT_BARRIER_SPHERE,
    "PS_CSAT_BARRIER_CYLINDER": _ACT_BARRIER_SPHERE,
    "PS_CSAT_TRAIL_SPAWNER": _ACT_TRAIL_SPAWNER,
    "PS_CSAT_EFFECT_SPAWNER": _ACT_EFFECT_SPAWNER,
    "PS_CSAT_BARRIER_PLANE": _ACT_BARRIER_PLANE,
    "PS_CSAT_CREATOR": _ACT_CREATOR,
}

#: PSPrototype 内部子结构偏移（FUN_1406f3180）
SYS_RENDERER = 0x000
SYS_EMITTER = 0x0D0
SYS_ANIMATION = 0x160
SYS_GENERAL = 0x1A0
SYS_DISTANCE = 0x1C0
SYS_SCALER = 0x1D0
SYS_NAME = 0x1E0
SYS_INTENSITIES = 0x1F0
SYS_COMPONENTS_COUNT = 0x200
SYS_COMPONENTS = 0x208


# ── 布局档案（莱服 / 寄服）───────────────────────────────────────────────
#
# 两服的 ``fx::PSPrototype`` 不是同一份布局。寄服 ``WorldOfWarships64.exe``
# （13357625）的系统结构是 **0x1C8** 字节，莱服 ``Korabli64.exe``（26.11PT1）
# 是 0x210。反编译依据（寄服）：
#
# ===========================  ============================================
# 函数                         作用
# ===========================  ============================================
# ``FUN_1408312f0``            ``fx::PSPrototype``（0x1C8）
# ``FUN_140834bd0``            ``fx::RendererPrototype``（0xA0）
# ``FUN_140835bc0``            ``fx::EmitterPrototype``（0x90，与莱服一致）
# ``FUN_140836220``            ``fx::AnimationPrototype``（0x40）
# ``FUN_1408367c0``            ``fx::GeneralPrototype``（0x18）
# ``FUN_140836b50``            ``fx::DistancePrototype``（0x10）
# ``FUN_140836fc0``            ``fx::IntensitiesPrototype``（通道数组）
# ``FUN_140841c10``            通道（configs 数组）
# ``FUN_140841990``            ``fx::IntensityConfig``（0x20）
# ``FUN_1408371d0``            ``ComponentPrototype`` 分派
# ``FUN_140842fd0``            ``PS_CPAT_*`` 分派（type 数值见图）
# ``FUN_140843970``            ``PS_CSAT_*`` 分派
# ``FUN_14083f590``            ``PS_CT_LIGHT_SOURCE`` 载荷（→ 0x70 光源结构）
# ``FUN_140852710``            ``fx::LocalLightSourcePrototype``（0x70）
# ``FUN_140840d60``            ``fx::RampPrototype``（``{count; capacity; rel}`` + 8 字节点）
# ``FUN_1408414a0``            ``ValueGeneratorPrototype`` 分派
# ===========================  ============================================
#
# 与莱服的主要差异：
#
# * 渲染器**没有** ``particleMeshPath``，也没有按轴拆分的自旋/朝向标量；
#   ``customCenterOffset`` 是 Vector2；``yawRateRamp`` 是**裸 RampPrototype**
#   （直接 ``{count; capacity; rel}``，不再套一层 type/data）。
# * ``general`` 少 8 字节（没有 volumetricsVisibilityMode / 水体剔除等开关）。
# * ``animation.frameRateRamp`` 同样是裸 ramp。
# * **没有 ``scaler`` 子结构**。
# * 局部光源由 0x88 缩到 0x70（只有 color / radius 两个动画）。
# * 动作枚举数值与莱服不同：寄服 ``PS_CPAT`` 多了 ``PS_CPAT_VELOCITY_FIELD``
#   且插在 ``PS_CPAT_BARRIER_BOX`` 之前；``PS_CSAT`` 去掉了
#   ``PS_CSAT_EFFECT_SPAWNER`` 并多了 ``PS_CSAT_VELOCITY_FIELD``。
# * ``PS_CT_DECAL_SOURCE`` 的结构没还原，载荷按原字节保留（不解析、不输出）。

#: 寄服 RendererPrototype（0xA0）
WG_RENDERER_FIELDS: Tuple[Tuple[str, int, str], ...] = (
    ("textureName0", 0x00, "string"),
    ("textureName1", 0x10, "string"),
    ("yawRateRamp", 0x20, "ramp"),
    ("explicitOrientation", 0x30, "vec3"),
    ("customCenterOffset", 0x3C, "vec2"),
    ("spinRateRange", 0x44, "f32"),
    ("spinRateBase", 0x48, "f32"),
    ("lightingShineness", 0x4C, "f32"),
    ("initialOrientationRange", 0x50, "f32"),
    ("lightingAmbient", 0x54, "f32"),
    ("initialOrientationBase", 0x58, "f32"),
    ("hideStartCos", 0x5C, "f32"),
    ("scaleX", 0x60, "f32"),
    ("_padRenderer64", 0x64, "pad4"),
    ("lightingTransmission", 0x68, "f32"),
    ("lightWrapAmount", 0x6C, "f32"),
    ("shadowsStrength", 0x70, "f32"),
    ("opacityMultiplier", 0x74, "f32"),
    ("hideSpeed", 0x78, "f32"),
    ("softParticleDepthScale", 0x7C, "f32"),
    ("rotationCenter", 0x80, "enum:PS_RRC"),
    ("lightingType", 0x84, "enum:PS_RLT"),
    ("blendType", 0x88, "enum:PS_RBT"),
    ("sortType", 0x8C, "enum:PS_RST"),
    ("tilingU", 0x90, "f32"),
    ("tilingV", 0x94, "f32"),
    ("explicitOrientationLocal", 0x98, "bool"),
    ("billboard", 0x99, "bool"),
    ("velocityOriented", 0x9A, "bool"),
    ("background", 0x9B, "bool"),
    ("flipTexcoordU", 0x9C, "bool"),
    ("flipTexcoordV", 0x9D, "bool"),
    ("_padRenderer", 0x9E, "pad2"),
)

#: 寄服 GeneralPrototype（0x18）
WG_GENERAL_FIELDS: Tuple[Tuple[str, int, str], ...] = (
    ("capacity", 0x00, "i32"),
    ("maxInstancesCount", 0x04, "i32"),
    ("maxParticleAge", 0x08, "f32"),
    ("cameraAttachOffset", 0x0C, "f32"),
    ("coordinateStyle", 0x10, "enum:PS_PCS"),
    ("reflectionVisible", 0x14, "bool"),
    ("prewarm", 0x15, "bool"),
    ("_padGeneral", 0x16, "pad2"),
)

#: 寄服 AnimationPrototype（0x40）
WG_ANIMATION_FIELDS: Tuple[Tuple[str, int, str], ...] = (
    ("frameRateRamp", 0x00, "ramp"),
    ("motionVectorsTexture", 0x10, "string"),
    ("framesPerY", 0x20, "i32"),
    ("framesPerX", 0x24, "i32"),
    ("framesRangeBegin", 0x28, "i32"),
    ("framesRangeEnd", 0x2C, "i32"),
    ("animationPeriod", 0x30, "f32"),
    ("motionVectorsDistortion", 0x34, "f32"),
    ("animationType", 0x38, "enum:PS_PAT"),
    ("randomFrameOnly", 0x3C, "bool"),
    ("useEmissionAlphaFromMV", 0x3D, "bool"),
    ("_padAnimation", 0x3E, "pad2"),
)

#: 寄服 LocalLightSourcePrototype（0x70）
WG_LOCAL_LIGHT_FIELDS: Tuple[Tuple[str, int, str], ...] = (
    ("color", 0x40, "vec4"),
    ("localPosition", 0x50, "vec3"),
    ("radius", 0x60, "f32"),
    ("_padLightCone", 0x64, "pad4"),
    ("_padLightTail", 0x6A, "pad6"),
)

# ── 寄服动作载荷 ──────────────────────────────────────────────────────────
#
# 由 ``FUN_140842fd0``（粒子动作）/ ``FUN_140843970``（系统动作）的分支
# 与各自调用的字段注册函数对齐得到；``PS_CPAT`` / ``PS_CSAT`` 的 type 数值
# 直接从分派分支读出（见 :data:`WG_ACTION_TYPES`）。

_WG_ACT_DAMPFER: Tuple[Tuple[str, int, str], ...] = (
    ("velocityGenerator", 0x00, "value"),
    ("delay", 0x10, "f32"),
    ("_padDampfer", 0x14, "pad4"),
)

_WG_ACT_STREAM: Tuple[Tuple[str, int, str], ...] = (
    ("vector", 0x00, "vec3"),
    ("delay", 0x0C, "f32"),
    ("halfLife", 0x10, "f32"),
    ("switchCoordinateStyle", 0x14, "bool"),
    ("_padStream", 0x15, "pad3"),
)

_WG_ACT_JITTER: Tuple[Tuple[str, int, str], ...] = (
    ("velocityGenerator", 0x00, "vector"),
    ("positionGenerator", 0x10, "vector"),
    ("delay", 0x20, "f32"),
    ("affectPosition", 0x24, "bool"),
    ("affectVelocity", 0x25, "bool"),
    ("_padJitter", 0x26, "pad2"),
)

_WG_ACT_FORCE: Tuple[Tuple[str, int, str], ...] = (
    ("forceXGenerator", 0x00, "value"),
    ("forceYGenerator", 0x10, "value"),
    ("forceZGenerator", 0x20, "value"),
    ("delay", 0x30, "f32"),
    ("_padForce", 0x34, "pad4"),
)

#: 寄服 ``PS_CPAT_RESIZER``：只有 delay 在反编译里登记了名字，后两个标量
#: 按数据形状（0.4/1.2、5.0/1000.0 这类组合）取 rate / targetSize
_WG_ACT_RESIZER: Tuple[Tuple[str, int, str], ...] = (
    ("delay", 0x00, "f32"),
    ("rate", 0x04, "f32"),
    ("targetSize", 0x08, "f32"),
)

_WG_ACT_ORBITOR: Tuple[Tuple[str, int, str], ...] = (
    ("angularVelocityGenerator", 0x00, "value"),
    ("point", 0x10, "vec3"),
    ("axis", 0x1C, "vec3"),
    ("delay", 0x28, "f32"),
    ("affectPosition", 0x2C, "bool"),
    ("affectVelocity", 0x2D, "bool"),
    ("_padOrbitor", 0x2E, "pad2"),
)

_WG_ACT_SCALER: Tuple[Tuple[str, int, str], ...] = (
    ("sizeGenerator", 0x00, "value"),
    ("scaleXGenerator", 0x10, "value"),
    ("delay", 0x20, "f32"),
    ("_padScaler", 0x24, "pad4"),
)

_WG_ACT_TINT: Tuple[Tuple[str, int, str], ...] = (
    ("tint", 0x00, "tintpoints"),
    ("delay", 0x10, "f32"),
    ("period", 0x14, "f32"),
    ("repeat", 0x18, "bool"),
    ("useVelocity", 0x19, "bool"),
    ("_padTint", 0x1A, "pad6"),
)

_WG_ACT_ALPHA_SETTER: Tuple[Tuple[str, int, str], ...] = (
    ("ramp", 0x00, "ramp"),
    ("delay", 0x10, "f32"),
    ("_padAlpha", 0x14, "pad4"),
)

_WG_ACT_MAGNET: Tuple[Tuple[str, int, str], ...] = (
    ("attractorPoint", 0x00, "vec3"),
    ("delay", 0x0C, "f32"),
    ("minimalDistance", 0x10, "f32"),
    ("strength", 0x14, "f32"),
)

_WG_ACT_BARRIER_BOX: Tuple[Tuple[str, int, str], ...] = (
    ("effectName", 0x00, "string"),
    ("opposite", 0x10, "vec3"),
    ("corner", 0x1C, "vec3"),
    ("strength", 0x28, "f32"),
    ("stopAge", 0x2C, "f32"),
    ("reaction", 0x30, "i32"),
    ("delay", 0x34, "f32"),
)

_WG_ACT_BARRIER_SPHERE: Tuple[Tuple[str, int, str], ...] = (
    ("effectName", 0x00, "string"),
    ("position", 0x10, "vec3"),
    ("reaction", 0x1C, "i32"),
    ("strength", 0x20, "f32"),
    ("stopAge", 0x24, "f32"),
    ("delay", 0x28, "f32"),
    ("radius", 0x2C, "f32"),
)

_WG_ACT_BARRIER_PLANE: Tuple[Tuple[str, int, str], ...] = (
    ("effectName", 0x00, "string"),
    ("planeEquation", 0x10, "vec4"),
    ("reaction", 0x20, "i32"),
    ("strength", 0x24, "f32"),
    ("stopAge", 0x28, "f32"),
    ("delay", 0x2C, "f32"),
    ("useWorldSpace", 0x30, "bool"),
    ("_padPlane", 0x31, "pad7"),
)

_WG_ACT_CREATOR: Tuple[Tuple[str, int, str], ...] = (
    ("rateRamp", 0x00, "ramp"),
    ("initialPositionGenerator", 0x10, "vector"),
    ("initialVelocityGenerator", 0x20, "vector"),
    ("systemAgeLimitMin", 0x30, "f32"),
    ("systemAgeLimitMax", 0x34, "f32"),
    ("velocityInheritanceFactor", 0x38, "f32"),
    ("minRandomRateBound", 0x3C, "u32"),
    ("repeated", 0x40, "bool"),
    ("useSmoothRate", 0x41, "bool"),
    ("useWorldCoordinates", 0x42, "bool"),
    ("_padCreator", 0x43, "pad5"),
)

_WG_ACT_TRAIL_SPAWNER: Tuple[Tuple[str, int, str], ...] = (
    ("trailRamp", 0x00, "ramp"),
    ("trailName", 0x10, "string"),
)

_WG_ACT_VELOCITY_FIELD: Tuple[Tuple[str, int, str], ...] = (
    ("topLeftFront", 0x00, "vec3"),
    ("bottomRightBack", 0x0C, "vec3"),
    ("stopAge", 0x18, "f32"),
    ("delay", 0x1C, "f32"),
    ("velocityScale", 0x20, "f32"),
    ("influence", 0x24, "f32"),
    ("fieldSourceName", 0x28, "string"),
)

#: 寄服 ``PS_CSAT_TRAIL_SPAWNER``（0x20）：裸 ramp + 目标分区字符串
WG_ACTION_FIELDS: Dict[str, Tuple[Tuple[str, int, str], ...]] = {
    "PS_CPAT_DAMPFER": _WG_ACT_DAMPFER,
    "PS_CPAT_STREAM": _WG_ACT_STREAM,
    "PS_CPAT_JITTER": _WG_ACT_JITTER,
    "PS_CPAT_FORCE": _WG_ACT_FORCE,
    "PS_CPAT_RESIZER": _WG_ACT_RESIZER,
    "PS_CPAT_ORBITOR": _WG_ACT_ORBITOR,
    "PS_CPAT_SCALER": _WG_ACT_SCALER,
    "PS_CPAT_TINT_SHADER": _WG_ACT_TINT,
    "PS_CPAT_ALPHA_SETTER": _WG_ACT_ALPHA_SETTER,
    "PS_CPAT_MAGNET": _WG_ACT_MAGNET,
    "PS_CPAT_BARRIER_BOX": _WG_ACT_BARRIER_BOX,
    "PS_CPAT_BARRIER_SPHERE": _WG_ACT_BARRIER_SPHERE,
    "PS_CPAT_BARRIER_CYLINDER": _WG_ACT_BARRIER_SPHERE,
    "PS_CPAT_VELOCITY_FIELD": _WG_ACT_VELOCITY_FIELD,
    "PS_CSAT_DAMPFER": _WG_ACT_DAMPFER,
    "PS_CSAT_STREAM": _WG_ACT_STREAM,
    "PS_CSAT_JITTER": _WG_ACT_JITTER,
    "PS_CSAT_FORCE": _WG_ACT_FORCE,
    "PS_CSAT_ORBITOR": _WG_ACT_ORBITOR,
    "PS_CSAT_MAGNET": _WG_ACT_MAGNET,
    "PS_CSAT_BARRIER_BOX": _WG_ACT_BARRIER_BOX,
    "PS_CSAT_BARRIER_SPHERE": _WG_ACT_BARRIER_SPHERE,
    "PS_CSAT_BARRIER_CYLINDER": _WG_ACT_BARRIER_SPHERE,
    "PS_CSAT_BARRIER_PLANE": _WG_ACT_BARRIER_PLANE,
    "PS_CSAT_CREATOR": _WG_ACT_CREATOR,
    "PS_CSAT_TRAIL_SPAWNER": _WG_ACT_TRAIL_SPAWNER,
    "PS_CSAT_VELOCITY_FIELD": _WG_ACT_VELOCITY_FIELD,
}


class _Layout:
    """一套服务器布局档案（字段表 + 偏移 + 枚举表名）。"""

    __slots__ = (
        "key", "label", "system_size", "sys_emitter", "sys_animation",
        "sys_general", "sys_distance", "sys_scaler", "sys_name",
        "sys_intensities", "sys_components_count", "sys_components_rel",
        "renderer_fields", "emitter_generators", "emitter_fields",
        "animation_fields", "general_fields", "distance_fields",
        "action_fields", "cpat_table", "csat_table", "valg_type_table",
        "ramp_value_first",
        "light_fields", "light_size", "light_flag_offsets", "light_marks",
        "decal_alpha", "decal_rel", "decal_fields", "decal_textures",
    )

    def __init__(self, **kw: Any) -> None:
        for name in self.__slots__:
            setattr(self, name, kw[name])


LESTA_LAYOUT = _Layout(
    key="Lesta",
    label="莱服（Korabli）",
    system_size=SYSTEM_SIZE,
    sys_emitter=SYS_EMITTER,
    sys_animation=SYS_ANIMATION,
    sys_general=SYS_GENERAL,
    sys_distance=SYS_DISTANCE,
    sys_scaler=SYS_SCALER,
    sys_name=SYS_NAME,
    sys_intensities=SYS_INTENSITIES,
    sys_components_count=SYS_COMPONENTS_COUNT,
    sys_components_rel=SYS_COMPONENTS,
    renderer_fields=RENDERER_FIELDS,
    emitter_generators=EMITTER_GENERATORS,
    emitter_fields=EMITTER_FIELDS,
    animation_fields=ANIMATION_FIELDS,
    general_fields=GENERAL_FIELDS,
    distance_fields=DISTANCE_FIELDS,
    action_fields=ACTION_FIELDS,
    cpat_table="PS_CPAT",
    csat_table="PS_CSAT",
    valg_type_table="PS_VALG_TYPE",
    ramp_value_first=False,
    light_fields=None,        # 回填：LOCAL_LIGHT_FIELDS（定义在光照段）
    light_size=None,          # 回填：LOCAL_LIGHT_SIZE
    light_flag_offsets=(0x84, 0x85, 0x86),
    light_marks=(0x5C, 0x80),
    decal_alpha=0x48,
    decal_rel=0x58,
    decal_fields=None,        # 回填：DECAL_FIELDS
    decal_textures=0x10,
)

WG_LAYOUT = _Layout(
    key="Wargaming",
    label="寄服（World of Warships）",
    system_size=0x1C8,
    sys_emitter=0x0A0,
    sys_animation=0x130,
    sys_general=0x170,
    sys_distance=0x188,
    sys_scaler=0,             # 寄服没有 scaler 子结构
    sys_name=0x198,
    sys_intensities=0x1A8,
    sys_components_count=0x1B8,
    sys_components_rel=0x1C0,
    renderer_fields=WG_RENDERER_FIELDS,
    emitter_generators=EMITTER_GENERATORS,
    emitter_fields=EMITTER_FIELDS,
    animation_fields=WG_ANIMATION_FIELDS,
    general_fields=WG_GENERAL_FIELDS,
    distance_fields=DISTANCE_FIELDS,
    action_fields=WG_ACTION_FIELDS,
    cpat_table="WG_PS_CPAT",
    csat_table="WG_PS_CSAT",
    valg_type_table="WG_PS_VALG_TYPE",
    ramp_value_first=True,
    light_fields=WG_LOCAL_LIGHT_FIELDS,
    light_size=0x70,
    light_flag_offsets=(0x68, 0x69),
    light_marks=(),
    decal_alpha=-1,           # 未还原：不做解析，字节留在 raw 里
    decal_rel=-1,
    decal_fields=None,
    decal_textures=-1,
)

#: 布局档案注册表（键 = :func:`uncode_assets.types.get_wows_type` 的返回值）
LAYOUTS: Dict[str, _Layout] = {
    "Lesta": LESTA_LAYOUT,
    "Wargaming": WG_LAYOUT,
    "Legacy": LESTA_LAYOUT,
}


def current_layout(wows_type: Optional[str] = None) -> _Layout:
    """返回当前线程的布局档案（``None`` → 用 :func:`types.get_wows_type`）。"""
    if wows_type is None:
        from .types import get_wows_type
        wows_type = get_wows_type()
    return LAYOUTS.get(wows_type, LESTA_LAYOUT)



# ── 基础工具 ──────────────────────────────────────────────────────────────

class _Ctx:
    """解码上下文：原始字节 + 已覆盖位图（未覆盖的字节会输出到 raw）。

    ``journal`` 非 None 时记录本次解码写的覆盖区间，便于子结构解析失败时回滚。
    """

    __slots__ = ("data", "cover", "journal", "lay")

    def __init__(self, data: bytes, lay: Optional["_Layout"] = None) -> None:
        self.data = data
        self.cover = bytearray(len(data))
        self.journal: Optional[List[Tuple[int, int]]] = None
        self.lay = lay or LESTA_LAYOUT

    def check(self, off: int, size: int) -> None:
        if off < 0 or size < 0 or off + size > len(self.data):
            raise FxFormatError(
                f"越界读取 off=0x{off:X} size=0x{size:X} len=0x{len(self.data):X}")

    def mark(self, off: int, size: int) -> None:
        self.check(off, size)
        self.cover[off:off + size] = b"\x01" * size
        if self.journal is not None:
            self.journal.append((off, size))

    def rollback(self, journal: List[Tuple[int, int]]) -> None:
        for off, size in journal:
            if 0 <= off and off + size <= len(self.cover):
                self.cover[off:off + size] = bytes(size)


def _f32(d: bytes, off: int) -> float:
    return struct.unpack_from("<f", d, off)[0]


def _i32(d: bytes, off: int) -> int:
    return struct.unpack_from("<i", d, off)[0]


def _u32(d: bytes, off: int) -> int:
    return struct.unpack_from("<I", d, off)[0]


def _i64(d: bytes, off: int) -> int:
    return struct.unpack_from("<q", d, off)[0]


def enum_name(table: str, value: int) -> str:
    names = ENUMS.get(table)
    if names and 0 <= value < len(names):
        return names[value]
    return str(value)


def enum_value(table: str, text: Any, default: int = 0) -> int:
    if isinstance(text, bool):
        return int(text)
    if isinstance(text, (int, float)):
        return int(text)
    s = str(text or "").strip()
    if not s:
        return default
    try:
        return int(s, 0)
    except ValueError:
        pass
    names = ENUMS.get(table, ())
    if s in names:
        return names.index(s)
    for i, n in enumerate(names):
        if n.endswith("_" + s):
            return i
    raise FxFormatError(f"未知枚举值 {s!r}（表 {table}）")


def _vec3(d: bytes, off: int) -> Dict[str, float]:
    return {"x": _f32(d, off), "y": _f32(d, off + 4), "z": _f32(d, off + 8)}


def _vec4(d: bytes, off: int) -> Dict[str, float]:
    return {"x": _f32(d, off), "y": _f32(d, off + 4), "z": _f32(d, off + 8),
            "w": _f32(d, off + 0xC)}


# ── 字符串 ────────────────────────────────────────────────────────────────

def _decode_string(ctx: _Ctx, off: int, tag: str) -> Dict[str, Any]:
    ctx.check(off, 16)
    size = _u32(ctx.data, off)
    cap = _u32(ctx.data, off + 4)
    rel = _i64(ctx.data, off + 8)
    out: Dict[str, Any] = {}
    if size == 0:
        out["size"] = 0
        if cap:
            out["capacity"] = cap
        if rel:
            out["rel"] = rel
        ctx.mark(off, 16)
        return out
    if size > 0x10000:
        raise FxFormatError(f"{tag}: 字符串长度异常 {size}")
    pos = off + rel
    ctx.check(pos, size)
    raw = ctx.data[pos:pos + size]
    if not raw.endswith(b"\x00"):
        raise FxFormatError(f"{tag}: 字符串未以 NUL 结尾（size={size}）")
    body = raw.split(b"\x00", 1)[0]
    if any(c < 0x20 or c >= 0x7F for c in body):
        raise FxFormatError(f"{tag}: 字符串含不可打印字符")
    # 首个 NUL 之后只能是补齐用的 NUL（寄服的空串就是 size=2 的 `\\x00\\x00`）
    if raw[len(body):].strip(b"\x00"):
        raise FxFormatError(f"{tag}: 字符串 NUL 之后含非零字节")
    out.update({"text": body.decode("ascii"), "at": pos, "size": size})
    if cap:
        out["capacity"] = cap
    ctx.mark(off, 16)
    ctx.mark(pos, size)
    return out


def _encode_string(reg: bytearray, node: Dict[str, Any], off: int) -> None:
    size = int(node.get("size") or 0)
    pos = int(node.get("at") if node.get("at") is not None else off)
    text = str(node.get("text") or "").encode("ascii")
    struct.pack_into("<I", reg, off, size)
    struct.pack_into("<I", reg, off + 4, int(node.get("capacity") or 0))
    if size:
        if len(text) > size - 1:
            raise FxFormatError(
                f"字符串新长度 {len(text)} 超过原容量 {size - 1}"
                "（当前版本不支持改变长度）")
        reg[pos:pos + size] = b"\x00" * size
        reg[pos:pos + len(text)] = text
        struct.pack_into("<q", reg, off + 8, pos - off)
    else:
        struct.pack_into("<q", reg, off + 8, int(node.get("rel") or 0))


# ── 值生成器 ──────────────────────────────────────────────────────────────

def _decode_valuegen(ctx: _Ctx, off: int, tag: str) -> Dict[str, Any]:
    ctx.check(off, 16)
    vtype = _i32(ctx.data, off)
    capacity = _u32(ctx.data, off + 4)
    rel = _i64(ctx.data, off + 8)
    out: Dict[str, Any] = {"type": enum_name(ctx.lay.valg_type_table, vtype)}
    if capacity:
        out["capacity"] = capacity
    ctx.mark(off, 16)
    payload = off + rel
    if vtype not in (0, 1, 2, 3) or rel == 0 or payload < 0 or payload + 16 > len(ctx.data):
        if rel:
            out["rel"] = rel
        return out
    out["at"] = payload
    if vtype == 1:
        out["value"] = _f32(ctx.data, payload)
        ctx.mark(payload, 4)
    elif vtype == 0:
        out["from"] = _f32(ctx.data, payload)
        out["to"] = _f32(ctx.data, payload + 4)
        ctx.mark(payload, 8)
    elif vtype == 3:
        out["from"] = _f32(ctx.data, payload)
        out["to"] = _f32(ctx.data, payload + 4)
        ctx.mark(payload, 8)
    else:
        count = _u32(ctx.data, payload)
        rcap = _u32(ctx.data, payload + 4)
        ramp: Dict[str, Any] = {"count": count, "points": []}
        if rcap:
            ramp["capacity"] = rcap
        if count:
            prel = _i64(ctx.data, payload + 8)
            ptype = _u32(ctx.data, payload + 0x10)
            stype = _u32(ctx.data, payload + 0x14)
            ramp["parameterType"] = enum_name("PS_VALG_RAMP_PARAMETER", ptype)
            ramp["samplingType"] = enum_name("PS_VALG_RAMP_SAMPLING", stype)
            pts = payload + prel if prel else 0
            if pts and 0 <= pts < len(ctx.data) and count * 8 <= len(ctx.data) - pts:
                ctx.mark(payload, 8)
                ctx.mark(payload + 8, 8)
                ctx.mark(payload + 0x10, 8)
                ramp["at"] = pts
                for i in range(count):
                    p = pts + i * 8
                    a, b = _f32(ctx.data, p), _f32(ctx.data, p + 4)
                    if ctx.lay.ramp_value_first:
                        ramp["points"].append({"value": a, "time": b})
                    else:
                        ramp["points"].append({"time": a, "value": b})
                ctx.mark(pts, count * 8)
        out["ramp"] = ramp
    return out


def _encode_valuegen(reg: bytearray, node: Dict[str, Any], off: int,
                     valg_table: str = "PS_VALG_TYPE",
                     value_first: bool = False) -> None:
    vtype = enum_value(valg_table, node.get("type"), -1)
    struct.pack_into("<i", reg, off, vtype)
    struct.pack_into("<I", reg, off + 4, int(node.get("capacity") or 0))
    payload = int(node.get("at") or 0)
    if not payload:
        struct.pack_into("<q", reg, off + 8, int(node.get("rel") or 0))
        return
    struct.pack_into("<q", reg, off + 8, payload - off)
    if vtype == 1:
        struct.pack_into("<f", reg, payload, _num(node.get("value")))
    elif vtype in (0, 3):
        struct.pack_into("<f", reg, payload, _num(node.get("from")))
        struct.pack_into("<f", reg, payload + 4, _num(node.get("to")))
    elif vtype == 2:
        ramp = node.get("ramp")
        if not isinstance(ramp, dict):
            return
        pts = int(ramp.get("at") or 0)
        points = ramp.get("points") or []
        struct.pack_into("<I", reg, payload + 4, int(ramp.get("capacity") or 0))
        if not pts or "parameterType" not in ramp:
            # 无点或未解析：保留原始字节（由 raw 覆盖）
            return
        struct.pack_into("<I", reg, payload + 0x10,
                         enum_value("PS_VALG_RAMP_PARAMETER", ramp.get("parameterType"), 0))
        struct.pack_into("<I", reg, payload + 0x14,
                         enum_value("PS_VALG_RAMP_SAMPLING", ramp.get("samplingType"), 0))
        struct.pack_into("<I", reg, payload, len(points))
        struct.pack_into("<q", reg, payload + 8, pts - payload)
        for i, p in enumerate(points):
            first, second = (_num(p.get("value")), _num(p.get("time"))) if value_first \
                else (_num(p.get("time")), _num(p.get("value")))
            struct.pack_into("<f", reg, pts + i * 8, first)
            struct.pack_into("<f", reg, pts + i * 8 + 4, second)


# ── 向量生成器 ────────────────────────────────────────────────────────────

def _decode_vectgen(ctx: _Ctx, off: int, tag: str) -> Dict[str, Any]:
    ctx.check(off, 16)
    vtype = _i32(ctx.data, off)
    count = _u32(ctx.data, off + 4)
    rel = _i64(ctx.data, off + 8)
    out: Dict[str, Any] = {
        "type": enum_name("PS_VGT", vtype), "count": count, "prototypes": [],
    }
    ctx.mark(off, 16)
    if rel == 0 or count == 0:
        if rel:
            out["rel"] = rel
        return out
    base = off + rel
    if base < 0 or base + count * 0x10 > len(ctx.data):
        out["rel"] = rel
        out["invalid"] = True
        return out
    out["at"] = base
    for i in range(count):
        proto = base + i * 0x10
        if proto + 16 > len(ctx.data):
            break
        ptype = _i32(ctx.data, proto)
        prel = _i64(ctx.data, proto + 8)
        item: Dict[str, Any] = {"type": enum_name("PS_VGT", ptype)}
        ctx.mark(proto, 4)
        ctx.mark(proto + 8, 8)
        data = proto + prel
        if prel and 0 <= data < len(ctx.data):
            item["at"] = data
            if ptype == 1 and data + 12 <= len(ctx.data):  # POINT：vec3
                item["point"] = _vec3(ctx.data, data)
                ctx.mark(data, 12)
            elif ptype == 4 and data + 24 <= len(ctx.data):  # LINE：两个 vec3
                item["from"] = _vec3(ctx.data, data)
                item["to"] = _vec3(ctx.data, data + 12)
                ctx.mark(data, 24)
            elif ptype == 3 and data + 16 <= len(ctx.data):  # SPHERE：中心 + 半径
                item["center"] = _vec3(ctx.data, data)
                item["radius"] = _f32(ctx.data, data + 12)
                ctx.mark(data, 16)
            elif ptype == 0 and data + 24 <= len(ctx.data):  # BOX：两个对角点
                item["corner"] = _vec3(ctx.data, data)
                item["opposite"] = _vec3(ctx.data, data + 12)
                ctx.mark(data, 24)
            elif ptype == 2 and data + 0x3C <= len(ctx.data):  # CYLINDER
                item["corner"] = _vec3(ctx.data, data)
                item["maxRadius"] = _f32(ctx.data, data + 0x0C)
                item["basisU"] = _vec3(ctx.data, data + 0x10)
                item["minRadius"] = _f32(ctx.data, data + 0x1C)
                item["basisV"] = _vec3(ctx.data, data + 0x20)
                item["difference"] = _vec3(ctx.data, data + 0x2C)
                item["scale"] = _f32(ctx.data, data + 0x38)
                ctx.mark(data, 0x3C)
        out["prototypes"].append(item)
    return out


def _encode_vectgen(reg: bytearray, node: Dict[str, Any], off: int) -> None:
    vtype = enum_value("PS_VGT", node.get("type"), -1)
    protos = node.get("prototypes") or []
    base = int(node.get("at") or 0)
    struct.pack_into("<i", reg, off, vtype)
    struct.pack_into("<I", reg, off + 4, len(protos) or int(node.get("count") or 0))
    if not base:
        struct.pack_into("<q", reg, off + 8, int(node.get("rel") or 0))
        return
    struct.pack_into("<q", reg, off + 8, base - off)
    for i, item in enumerate(protos):
        proto = base + i * 0x10
        ptype = enum_value("PS_VGT", item.get("type"), -1)
        data = int(item.get("at") or 0)
        struct.pack_into("<i", reg, proto, ptype)
        struct.pack_into("<q", reg, proto + 8, (data - proto) if data else 0)
        if not data:
            continue
        point = item.get("point")
        if isinstance(point, dict):
            _write_vec3(reg, data, point)
        center = item.get("center")
        if isinstance(center, dict):
            _write_vec3(reg, data, center)
        if isinstance(item.get("radius"), (int, float)):
            struct.pack_into("<f", reg, data + 12, _num(item["radius"]))
        for key, rel in (("from", 0), ("to", 12)):
            v = item.get(key)
            if isinstance(v, dict):
                _write_vec3(reg, data + rel, v)
        corner = item.get("corner")
        if isinstance(corner, dict):
            _write_vec3(reg, data, corner)
        opposite = item.get("opposite")
        if isinstance(opposite, dict):
            _write_vec3(reg, data + 12, opposite)
        for key, rel in (("basisU", 0x10), ("basisV", 0x20), ("difference", 0x2C)):
            v = item.get(key)
            if isinstance(v, dict):
                _write_vec3(reg, data + rel, v)
        for key, rel in (("maxRadius", 0x0C), ("minRadius", 0x1C), ("scale", 0x38)):
            v = item.get(key)
            if isinstance(v, (int, float)):
                struct.pack_into("<f", reg, data + rel, _num(v))


def _num(value: Any, default: float = 0.0) -> float:
    """数值转换（注意 ``-0.0`` 是合法的，不能用 ``or`` 兜底）。"""
    return float(default if value is None else value)


# ── 内联点数组（ramp / tint）─────────────────────────────────────────────

#: 元素类型 → (元素长度, 类型)
_POINT_STRIDE = {"ramp": 8, "tintpoints": 0x14}


def _decode_point_array(ctx: _Ctx, off: int, tag: str, kind: str) -> Dict[str, Any]:
    """``{u32 count; u32 capacity; i64 rel}`` + 元素数组（rel 基准 = 该字段自身）。"""
    ctx.check(off, 16)
    count = _u32(ctx.data, off)
    capacity = _u32(ctx.data, off + 4)
    rel = _i64(ctx.data, off + 8)
    stride = _POINT_STRIDE[kind]
    out: Dict[str, Any] = {"count": count, "points": []}
    if capacity:
        out["capacity"] = capacity
    ctx.mark(off, 16)
    if count == 0:
        if rel:
            out["rel"] = rel
        return out
    if count > 0x4000:
        raise FxFormatError(f"{tag}: 点数异常 {count}")
    base = off + rel if rel else 0
    if not base or base < 0 or base + count * stride > len(ctx.data):
        out["invalid"] = True
        if rel:
            out["rel"] = rel
        return out
    out["at"] = base
    value_first = kind == "ramp" and ctx.lay.ramp_value_first
    for i in range(count):
        p = base + i * stride
        if kind == "ramp":
            a, b = _f32(ctx.data, p), _f32(ctx.data, p + 4)
            if value_first:
                out["points"].append({"value": a, "time": b})
            else:
                out["points"].append({"time": a, "value": b})
        else:
            out["points"].append({"color": _vec4(ctx.data, p), "time": _f32(ctx.data, p + 0x10)})
    ctx.mark(base, count * stride)
    return out


def _encode_point_array(reg: bytearray, node: Dict[str, Any], off: int, kind: str,
                        value_first: bool = False) -> None:
    stride = _POINT_STRIDE[kind]
    base = int(node.get("at") or 0)
    points = node.get("points") or []
    struct.pack_into("<I", reg, off, len(points) if points else int(node.get("count") or 0))
    struct.pack_into("<I", reg, off + 4, int(node.get("capacity") or 0))
    if not base:
        struct.pack_into("<q", reg, off + 8, int(node.get("rel") or 0))
        return
    struct.pack_into("<q", reg, off + 8, base - off)
    for i, p in enumerate(points):
        pos = base + i * stride
        if kind == "ramp":
            first, second = (_num(p.get("value")), _num(p.get("time"))) if value_first \
                else (_num(p.get("time")), _num(p.get("value")))
            struct.pack_into("<f", reg, pos, first)
            struct.pack_into("<f", reg, pos + 4, second)
        else:
            color = p.get("color")
            if isinstance(color, dict):
                for k, rel in (("x", 0), ("y", 4), ("z", 8), ("w", 0xC)):
                    struct.pack_into("<f", reg, pos + rel, _num(color.get(k)))
            struct.pack_into("<f", reg, pos + 0x10, _num(p.get("time")))


def _write_vec4(reg: bytearray, off: int, v: Dict[str, Any]) -> None:
    for k, rel in (("x", 0), ("y", 4), ("z", 8), ("w", 0xC)):
        struct.pack_into("<f", reg, off + rel, _num(v.get(k)))


def _write_vec3(reg: bytearray, off: int, v: Dict[str, Any]) -> None:
    struct.pack_into("<f", reg, off, _num(v.get("x")))
    struct.pack_into("<f", reg, off + 4, _num(v.get("y")))
    struct.pack_into("<f", reg, off + 8, _num(v.get("z")))


# ── 数组描述符 / 强度与距离配置 ───────────────────────────────────────────
#
# 引擎里的可变长数组统一是 ``{u32 count; u32 capacity; i64 rel}``
# （16 字节，rel 基准见各调用点）。``DistancePrototype`` / ``ScalerPrototype``
# 是唯一例外：数组从 +0x04 开始且**没有 capacity**，即 ``{u32 count; i64 rel}``。

#: fx::IntensityConfig / DistanceConfig 元素长度
CONFIG_SIZE = 0x20
#: 曲线点（fx::IntPoint）长度 = {f32 time; f32 value}
CURVE_POINT_SIZE = 8
#: 颜色关键帧（光照 colorAnimation）长度 = {f32 time; vec4 color}
CURVE_COLOR_SIZE = 0x14
#: fx::LocalLightSourcePrototype 长度
LOCAL_LIGHT_SIZE = 0x88
#: 光照动画（fx::ColorAnimation / RadiusAnimation）长度
LIGHT_ANIM_SIZE = 0x20
#: 光照动画内层数组描述符偏移（rel 基准 = 该偏移处）
LIGHT_ANIM_POINTS = 0x10


def _decode_array_header(ctx: _Ctx, off: int, with_capacity: bool = True):
    """读数组描述符，返回 ``(count, capacity, rel)`` 并标记已覆盖字节。

    带 capacity：``{u32 count; u32 capacity; i64 rel}``（16 字节，rel 在 +8）。
    不带 capacity：``{u32 count; i64 rel}``（12 字节，rel 在 +4）。
    """
    if with_capacity:
        ctx.check(off, 16)
        count = _u32(ctx.data, off)
        capacity = _u32(ctx.data, off + 4)
        rel = _i64(ctx.data, off + 8)
        ctx.mark(off, 16)
        return count, capacity, rel
    ctx.check(off, 12)
    count = _u32(ctx.data, off)
    rel = _i64(ctx.data, off + 4)
    ctx.mark(off, 12)
    return count, 0, rel


def _array_body(ctx: _Ctx, header_off: int, rel_base: int, stride: int, tag: str,
                with_capacity: bool = True):
    """返回 ``(node, at)``；node 含 count/capacity/at，越界时抛 :class:`FxFormatError`。"""
    count, capacity, rel = _decode_array_header(ctx, header_off, with_capacity)
    node: Dict[str, Any] = {"count": count}
    if capacity:
        node["capacity"] = capacity
    if not count or not rel:
        if rel:
            node["rel"] = rel
        return node, 0
    at = rel_base + rel
    need = count * stride
    if at < 0 or at + need > len(ctx.data):
        node["rel"] = rel
        node["invalid"] = True
        return node, 0
    node["at"] = at
    return node, at


def _decode_curve_points(ctx: _Ctx, header_off: int, rel_base: int,
                         tag: str, stride: int = CURVE_POINT_SIZE,
                         value_first: bool = False) -> Dict[str, Any]:
    """``{count; capacity; rel}`` → ``{count, at, points}``。

    ``stride == CURVE_POINT_SIZE`` 时点是 ``{time, value}``（寄服 ``value_first``
    则是 ``{value, time}``）；``stride == CURVE_COLOR_SIZE`` 时点是
    ``{time, color(vec4)}``（光照 colorAnimation）。
    """
    node, at = _array_body(ctx, header_off, rel_base, stride, tag)
    if not at:
        node.setdefault("points", [])
        return node
    points: List[Dict[str, Any]] = []
    for i in range(node["count"]):
        p = at + i * stride
        if stride == CURVE_COLOR_SIZE:
            points.append({"time": _f32(ctx.data, p), "color": _vec4(ctx.data, p + 4)})
            continue
        a, b = _f32(ctx.data, p), _f32(ctx.data, p + 4)
        points.append({"value": a, "time": b} if value_first else {"time": a, "value": b})
    node["points"] = points
    ctx.mark(at, node["count"] * stride)
    return node


def _decode_u32_values(ctx: _Ctx, header_off: int, rel_base: int,
                       tag: str) -> Dict[str, Any]:
    """``{count; capacity; rel}`` → ``{count, at, values:[u32]}``。"""
    node, at = _array_body(ctx, header_off, rel_base, 4, tag)
    if not at:
        node.setdefault("values", [])
        return node
    node["values"] = [_u32(ctx.data, at + i * 4) for i in range(node["count"])]
    ctx.mark(at, node["count"] * 4)
    return node


def _decode_config(ctx: _Ctx, pos: int, tag: str) -> Dict[str, Any]:
    """单个配置项（0x20）：曲线点数组 + 标志位数组（rel 基准 = 本元素）。"""
    node: Dict[str, Any] = {}
    try:
        node["ramp"] = _decode_curve_points(ctx, pos, pos, tag + ".ramp",
                                            value_first=ctx.lay.ramp_value_first)
        node["flags"] = _decode_u32_values(ctx, pos + 0x10, pos, tag + ".flags")
    except FxFormatError:
        return {"invalid": True}
    return node


def _decode_configs(ctx: _Ctx, header_off: int, rel_base: int, tag: str,
                    with_capacity: bool = True) -> Dict[str, Any]:
    """配置项数组（元素 0x20）。"""
    node, at = _array_body(ctx, header_off, rel_base, CONFIG_SIZE, tag, with_capacity)
    node["items"] = []
    if not at:
        return node
    for i in range(node["count"]):
        node["items"].append(_decode_config(ctx, at + i * CONFIG_SIZE, f"{tag}[{i}]"))
    return node


def _encode_array_header(reg: bytearray, off: int, node: Dict[str, Any],
                         rel_base: int, count: int, with_capacity: bool = True) -> None:
    struct.pack_into("<I", reg, off, count)
    rel_slot = off + 8
    if with_capacity:
        struct.pack_into("<I", reg, off + 4, int(node.get("capacity") or 0))
    else:
        rel_slot = off + 4
    at = int(node.get("at") or 0)
    if at and count:
        struct.pack_into("<q", reg, rel_slot, at - rel_base)
    else:
        struct.pack_into("<q", reg, rel_slot, int(node.get("rel") or 0))


def _encode_curve_points(reg: bytearray, header_off: int, node: Dict[str, Any],
                         rel_base: int, stride: int = CURVE_POINT_SIZE,
                         value_first: bool = False) -> None:
    points = [p for p in (node.get("points") or []) if isinstance(p, dict)]
    count = len(points) or int(node.get("count") or 0)
    _encode_array_header(reg, header_off, node, rel_base, count)
    at = int(node.get("at") or 0)
    if not (at and points):
        return
    for i, p in enumerate(points):
        pos = at + i * stride
        if stride == CURVE_COLOR_SIZE:
            struct.pack_into("<f", reg, pos, _num(p.get("time")))
            _write_vec4(reg, pos + 4, p.get("color") or {})
            continue
        first, second = (_num(p.get("value")), _num(p.get("time"))) if value_first \
            else (_num(p.get("time")), _num(p.get("value")))
        struct.pack_into("<f", reg, pos, first)
        struct.pack_into("<f", reg, pos + 4, second)


def _encode_u32_values(reg: bytearray, header_off: int, node: Dict[str, Any],
                       rel_base: int) -> None:
    values = list(node.get("values") or [])
    count = len(values) or int(node.get("count") or 0)
    _encode_array_header(reg, header_off, node, rel_base, count)
    at = int(node.get("at") or 0)
    if not (at and values):
        return
    for i, v in enumerate(values):
        struct.pack_into("<I", reg, at + i * 4, int(v))


def _encode_configs(reg: bytearray, header_off: int, node: Dict[str, Any],
                    rel_base: int, with_capacity: bool = True,
                    value_first: bool = False) -> None:
    items = [it for it in (node.get("items") or []) if isinstance(it, dict)]
    count = len(items) or int(node.get("count") or 0)
    _encode_array_header(reg, header_off, node, rel_base, count, with_capacity)
    at = int(node.get("at") or 0)
    if not (at and items):
        return
    for i, item in enumerate(items):
        pos = at + i * CONFIG_SIZE
        _encode_curve_points(reg, pos, item.get("ramp") or {}, pos, value_first=value_first)
        _encode_u32_values(reg, pos + 0x10, item.get("flags") or {}, pos)


# ── 光照 / 贴花组件载荷 ───────────────────────────────────────────────────
#
# PS_CT_LIGHT_SOURCE（``FUN_14070e990`` → ``FUN_1401c54b0``）：
#
#   payload  ``{i32 kind; u32 pad; i64 rel}``，kind==0 时 ``payload+rel`` 是
#   ``fx::LocalLightSourcePrototype``（0x88）。
#
# PS_CT_DECAL_SOURCE（``FUN_140717b90`` → ``FUN_1401c5e70``）：
#
#   payload  ``{i32 kind; ...; ValueGenerator alpha @0x48; i64 rel @0x58}``。
#
# 注意：``colorAnimation`` / ``radiusAnimation`` 的曲线数组 rel 基准 =
# **该动画结构 +0x10**（引擎把数组描述符自身的地址当基准）。

#: LocalLightSourcePrototype 中的标量字段
LOCAL_LIGHT_FIELDS: Tuple[Tuple[str, int, str], ...] = (
    ("color", 0x40, "vec4"),
    ("localPosition", 0x50, "vec3"),
    ("radius", 0x60, "f32"),
    ("innerAngle", 0x64, "f32"),
    ("outerAngle", 0x68, "f32"),
    ("falloff", 0x6C, "f32"),
    ("specularIntensity", 0x70, "f32"),
    ("visibleDistance", 0x74, "f32"),
    ("type", 0x78, "u32"),
    ("minQuality", 0x7C, "u32"),
)

#: 贴花结构字段
DECAL_FIELDS: Tuple[Tuple[str, int, str], ...] = (
    ("technique", 0x00, "u32"),
    ("influence", 0x04, "u32"),
    ("priority", 0x08, "u32"),
    ("alpha", 0x0C, "f32"),
)

# 布局档案里的光照/贴花字段表定义在上面，这里回填（寄服没有解析贴花）
LESTA_LAYOUT.light_fields = LOCAL_LIGHT_FIELDS
LESTA_LAYOUT.light_size = LOCAL_LIGHT_SIZE
LESTA_LAYOUT.decal_fields = DECAL_FIELDS


def _decode_light_anim(ctx: _Ctx, base: int, tag: str,
                       color: bool = False) -> Dict[str, Any]:
    """光照动画 ``{f32 duration; u32 repeated; 8B 保留; Array points@0x10}``。

    ``color=True``（colorAnimation）时点是 ``{time; vec4 color}``（0x14），
    否则是 ``{time; value}``（8）。两服都是 time 在前。
    """
    pos = base + LIGHT_ANIM_POINTS
    node: Dict[str, Any] = {
        "duration": _f32(ctx.data, base),
        "repeated": bool(_u32(ctx.data, base + 4)),
    }
    node.update(_decode_curve_points(
        ctx, pos, pos, tag, CURVE_COLOR_SIZE if color else CURVE_POINT_SIZE))
    ctx.mark(base, 8)
    ctx.mark(base + 8, LIGHT_ANIM_POINTS - 8)   # 恒为 0 的保留槽
    return node


def _decode_light_source(ctx: _Ctx, payload: int, item: Dict[str, Any],
                         lay: _Layout) -> None:
    """解码 ``PS_CT_LIGHT_SOURCE`` 载荷（kind 0 = 局部光源）。"""
    kind = _i32(ctx.data, payload)
    item["kind"] = kind
    ctx.mark(payload, 4)
    if kind != 0:
        return
    rel = _i64(ctx.data, payload + 8)
    ctx.mark(payload + 8, 8)
    if not rel:
        return
    base = payload + rel
    if base < 0 or base + (lay.light_size or LOCAL_LIGHT_SIZE) > len(ctx.data):
        return
    prev_journal = ctx.journal
    journal: List[Tuple[int, int]] = []
    ctx.journal = journal
    local: Dict[str, Any] = {}
    try:
        local["colorAnimation"] = _decode_light_anim(ctx, base + 0x00, "colorAnimation",
                                                     color=True)
        local["radiusAnimation"] = _decode_light_anim(ctx, base + LIGHT_ANIM_SIZE,
                                                      "radiusAnimation")
        for tag in ("colorAnimation", "radiusAnimation"):
            anim = local[tag]
            if anim["repeated"] not in (0, 1):
                raise FxFormatError(f"{tag}: repeated={anim['repeated']} 非法")
        _decode_fields(ctx, base, lay.light_fields, local)
        for off in lay.light_marks:
            ctx.mark(base + off, 4)
        names = ("animatedColor", "animatedRadius", "enabled")
        for name, off in zip(names, lay.light_flag_offsets):
            local[name] = bool(ctx.data[base + off])
        tail = len(lay.light_flag_offsets) + 1
        if ctx.data[base + lay.light_flag_offsets[-1] + 1]:
            local["reserved"] = ctx.data[base + lay.light_flag_offsets[-1] + 1]
        ctx.mark(base + lay.light_flag_offsets[0], tail)
    except (FxFormatError, struct.error):
        ctx.rollback(journal)
        ctx.journal = prev_journal
        return
    ctx.journal = prev_journal
    item["localLight"] = local
    item["fieldsAt"] = base


def _decode_decal_source(ctx: _Ctx, payload: int, item: Dict[str, Any],
                         lay: _Layout) -> None:
    """解码 ``PS_CT_DECAL_SOURCE`` 载荷（kind 0 = 贴花）。"""
    kind = _i32(ctx.data, payload)
    item["kind"] = kind
    ctx.mark(payload, 4)
    if kind != 0:
        return
    decal: Dict[str, Any] = {"transform": _u32(ctx.data, payload + 4)}
    ctx.mark(payload + 4, 4)
    decal["alpha"] = _decode_valuegen(ctx, payload + lay.decal_alpha, "alpha")
    rel = _i64(ctx.data, payload + lay.decal_rel)
    ctx.mark(payload + lay.decal_rel, 8)
    item["decal"] = decal
    if not rel:
        return
    base = payload + rel
    if base < 0 or base + 0x20 > len(ctx.data):
        return
    node: Dict[str, Any] = {}
    _decode_fields(ctx, base, lay.decal_fields, node)
    node["textures"] = _decode_string_array(ctx, base + lay.decal_textures, base,
                                            "textures")
    decal["decal"] = node


def _decode_string_array(ctx: _Ctx, header_off: int, rel_base: int,
                         tag: str) -> Dict[str, Any]:
    """``{count; capacity; rel}`` → 元素为 String 的数组。"""
    node, at = _array_body(ctx, header_off, rel_base, 16, tag)
    node["items"] = []
    if not at:
        return node
    for i in range(node["count"]):
        node["items"].append(_decode_string(ctx, at + i * 16, f"{tag}[{i}]"))
    return node


def _encode_string_array(reg: bytearray, header_off: int, rel_base: int,
                         node: Dict[str, Any]) -> None:
    items = [it for it in (node.get("items") or []) if isinstance(it, dict)]
    count = len(items) or int(node.get("count") or 0)
    _encode_array_header(reg, header_off, node, rel_base, count)
    at = int(node.get("at") or 0)
    if not (at and items):
        return
    for i, item in enumerate(items):
        _encode_string(reg, item, at + i * 16)


def _encode_light_source(reg: bytearray, payload: int, item: Dict[str, Any],
                         lay: _Layout) -> None:
    local = item.get("localLight")
    if not isinstance(local, dict):
        return
    struct.pack_into("<i", reg, payload, int(item.get("kind") or 0))
    base = int(item.get("fieldsAt") or 0)
    if not base:
        return
    struct.pack_into("<q", reg, payload + 8, base - payload)
    for tag, off, stride in (("colorAnimation", 0x00, CURVE_COLOR_SIZE),
                             ("radiusAnimation", LIGHT_ANIM_SIZE, CURVE_POINT_SIZE)):
        anim = local.get(tag)
        if not isinstance(anim, dict):
            continue
        pos = base + off
        struct.pack_into("<f", reg, pos, _num(anim.get("duration")))
        struct.pack_into("<I", reg, pos + 4, 1 if anim.get("repeated") else 0)
        reg[pos + 8:pos + LIGHT_ANIM_POINTS] = bytes(LIGHT_ANIM_POINTS - 8)
        _encode_curve_points(reg, pos + LIGHT_ANIM_POINTS, anim,
                             pos + LIGHT_ANIM_POINTS, stride)
    _encode_fields(reg, base, lay.light_fields, local, lay)
    for name, off in zip(("animatedColor", "animatedRadius", "enabled"),
                         lay.light_flag_offsets):
        reg[base + off] = 1 if local.get(name) else 0
    tail = lay.light_flag_offsets[-1] + 1
    if base + tail < len(reg):
        reg[base + tail] = int(local.get("reserved") or 0)


def _encode_decal_source(reg: bytearray, payload: int, item: Dict[str, Any],
                         lay: _Layout) -> None:
    decal = item.get("decal")
    if not isinstance(decal, dict):
        return
    struct.pack_into("<i", reg, payload, int(item.get("kind") or 0))
    struct.pack_into("<I", reg, payload + 4, int(decal.get("transform") or 0))
    alpha = decal.get("alpha")
    if isinstance(alpha, dict):
        _encode_valuegen(reg, alpha, payload + lay.decal_alpha, lay.valg_type_table,
                         lay.ramp_value_first)
    node = decal.get("decal")
    if not isinstance(node, dict):
        return
    base = int((node.get("textures") or {}).get("at") or 0)
    if not base:
        return
    # 贴花结构起点 = textures 数组所在位置 - 0x10
    start = base - lay.decal_textures
    struct.pack_into("<q", reg, payload + lay.decal_rel, start - payload)
    _encode_fields(reg, start, lay.decal_fields, node, lay)
    _encode_string_array(reg, start + lay.decal_textures, start,
                         node.get("textures") or {})


# ── 组件 ──────────────────────────────────────────────────────────────────

def _decode_components(ctx: _Ctx, sys_base: int, sys: Dict[str, Any],
                       lay: _Layout) -> None:
    holder: Dict[str, Any] = {}
    inode, base = _array_body(ctx, sys_base + lay.sys_components_count,
                              sys_base, 0x10, "components")
    holder.update(inode)
    holder["items"] = []
    sys["components"] = holder
    if not base:
        return
    holder["at"] = base
    for i in range(holder["count"]):
        off = base + i * 0x10
        ctype = _i32(ctx.data, off)
        crel = _i64(ctx.data, off + 8)
        item: Dict[str, Any] = {"type": enum_name("PS_CT", ctype)}
        ctx.mark(off, 4)
        ctx.mark(off + 8, 8)
        payload = off + crel
        if crel and 0 <= payload + 16 <= len(ctx.data):
            if ctype == 1:
                item["at"] = payload
                _decode_light_source(ctx, payload, item, lay)
            elif ctype == 2:
                if lay.decal_alpha < 0:
                    item["rel"] = crel
                else:
                    item["at"] = payload
                    _decode_decal_source(ctx, payload, item, lay)
            else:
                item["at"] = payload
                table = lay.cpat_table if ctype == 0 else lay.csat_table
                item["action"] = enum_name(table, _i32(ctx.data, payload))
                ctx.mark(payload, 4)
                _decode_action(ctx, item, lay)
        elif crel:
            item["rel"] = crel
        holder["items"].append(item)


def _decode_action(ctx: _Ctx, item: Dict[str, Any], lay: _Layout) -> None:
    """解析动作载荷指向的动作子结构。

    载荷 = ``{u32 actionType; u32 pad; i64 rel}``，子结构在 ``payload + rel``
    （基准 = 载荷自身地址）；子结构字段见各布局档案的 action 表。
    结构不符合预期（未还原的动作 / 偏移不同）时回滚覆盖标记，只保留动作类型，
    对应字节留在 ``raw`` 里，保证仍可无损回写。
    """
    payload = int(item.get("at") or 0)
    fields = lay.action_fields.get(str(item.get("action") or ""))
    if not fields or payload + 16 > len(ctx.data):
        return
    rel = _i64(ctx.data, payload + 8)
    cap = _u32(ctx.data, payload + 4)
    ctx.mark(payload, 8)
    if cap:
        item["capacity"] = cap
    sub = payload + rel
    if not rel or not (0 < sub < len(ctx.data)):
        return
    out: Dict[str, Any] = {}
    prev_journal = ctx.journal
    journal: List[Tuple[int, int]] = []
    ctx.journal = journal
    try:
        ctx.mark(payload + 8, 8)
        _decode_fields(ctx, sub, fields, out)
    except (FxFormatError, struct.error):
        ctx.rollback(journal)
        out = {}
    finally:
        ctx.journal = prev_journal
    if out:
        item["fieldsAt"] = sub
        item["fields"] = out
    else:
        item["rel"] = rel


def _encode_action(reg: bytearray, item: Dict[str, Any], lay: _Layout) -> None:
    fields = lay.action_fields.get(str(item.get("action") or ""))
    node = item.get("fields")
    payload = int(item.get("at") or 0)
    sub = int(item.get("fieldsAt") or 0)
    if not payload:
        return
    struct.pack_into("<I", reg, payload + 4, int(item.get("capacity") or 0))
    if sub:
        struct.pack_into("<q", reg, payload + 8, sub - payload)
    elif item.get("rel") is not None:
        struct.pack_into("<q", reg, payload + 8, int(item["rel"]))
    if not (fields and isinstance(node, dict) and sub):
        return
    _encode_fields(reg, sub, fields, node, lay)


def _encode_components(reg: bytearray, sys_base: int, node: Optional[Dict[str, Any]],
                       lay: _Layout) -> None:
    items = (node or {}).get("items") or []
    base = int((node or {}).get("at") or 0)
    _encode_array_header(reg, sys_base + lay.sys_components_count, node or {}, sys_base,
                         len(items) or int((node or {}).get("count") or 0))
    if not base:
        return
    for i, item in enumerate(items):
        off = base + i * 0x10
        ctype = enum_value("PS_CT", item.get("type"), -1)
        payload = int(item.get("at") or 0)
        struct.pack_into("<i", reg, off, ctype)
        if payload:
            struct.pack_into("<q", reg, off + 8, payload - off)
        elif item.get("rel") is not None:
            struct.pack_into("<q", reg, off + 8, int(item["rel"]))
        if not payload:
            continue
        if ctype == 1:
            _encode_light_source(reg, payload, item, lay)
        elif ctype == 2:
            _encode_decal_source(reg, payload, item, lay)
        elif item.get("action") is not None:
            table = lay.cpat_table if ctype == 0 else lay.csat_table
            struct.pack_into("<i", reg, payload, enum_value(table, item["action"], -1))
            _encode_action(reg, item, lay)


# ── 字段表分发 ────────────────────────────────────────────────────────────

def _decode_fields(ctx: _Ctx, base: int, fields: Sequence[Tuple[str, int, str]],
                   out: Dict[str, Any]) -> None:
    for name, off, kind in fields:
        pos = base + off
        if kind == "string":
            out[name] = _decode_string(ctx, pos, name)
        elif kind == "value":
            out[name] = _decode_valuegen(ctx, pos, name)
        elif kind == "vector":
            out[name] = _decode_vectgen(ctx, pos, name)
        elif kind == "vec3":
            out[name] = _vec3(ctx.data, pos)
            ctx.mark(pos, 12)
        elif kind == "vec2":
            out[name] = {"x": _f32(ctx.data, pos), "y": _f32(ctx.data, pos + 4)}
            ctx.mark(pos, 8)
        elif kind == "vec4":
            out[name] = _vec4(ctx.data, pos)
            ctx.mark(pos, 16)
        elif kind in _POINT_STRIDE:
            out[name] = _decode_point_array(ctx, pos, name, kind)
        elif kind == "f32":
            out[name] = _f32(ctx.data, pos)
            ctx.mark(pos, 4)
        elif kind == "i32":
            out[name] = _i32(ctx.data, pos)
            ctx.mark(pos, 4)
        elif kind == "u32":
            out[name] = _u32(ctx.data, pos)
            ctx.mark(pos, 4)
        elif kind == "u8":
            out[name] = ctx.data[pos]
            ctx.mark(pos, 1)
        elif kind.startswith("pad"):
            # 保留/对齐槽：恒定 0 时不出现在 XML 里，非 0 时按十六进制保存
            size = int(kind[3:] or 1)
            if pos + size > len(ctx.data):
                continue
            blob = ctx.data[pos:pos + size]
            if any(blob):
                out[name] = blob.hex()
            ctx.mark(pos, size)
        elif kind == "bool":
            out[name] = bool(ctx.data[pos])
            ctx.mark(pos, 1)
        elif kind.startswith("enum:"):
            out[name] = enum_name(kind[5:], _i32(ctx.data, pos))
            ctx.mark(pos, 4)
        else:
            raise FxFormatError(f"未知字段类型 {kind}")


def _encode_fields(reg: bytearray, base: int, fields: Sequence[Tuple[str, int, str]],
                   node: Dict[str, Any], lay: Optional[_Layout] = None) -> None:
    lay = lay or LESTA_LAYOUT
    for name, off, kind in fields:
        pos = base + off
        value = node.get(name)
        if value is None:
            continue
        if kind == "string":
            _encode_string(reg, value if isinstance(value, dict) else {"text": str(value)}, pos)
        elif kind == "value":
            _encode_valuegen(reg, value, pos, lay.valg_type_table, lay.ramp_value_first)
        elif kind == "vector":
            _encode_vectgen(reg, value, pos)
        elif kind == "vec3":
            _write_vec3(reg, pos, value)
        elif kind == "vec2":
            struct.pack_into("<f", reg, pos, _num(value.get("x")))
            struct.pack_into("<f", reg, pos + 4, _num(value.get("y")))
        elif kind == "vec4":
            _write_vec4(reg, pos, value)
        elif kind in _POINT_STRIDE:
            _encode_point_array(reg, value, pos, kind, lay.ramp_value_first)
        elif kind == "f32":
            struct.pack_into("<f", reg, pos, float(value))
        elif kind == "i32":
            struct.pack_into("<i", reg, pos, int(value))
        elif kind == "u32":
            struct.pack_into("<I", reg, pos, int(value))
        elif kind == "u8":
            reg[pos] = int(value) & 0xFF
        elif kind.startswith("pad"):
            size = int(kind[3:] or 1)
            blob = bytes.fromhex(str(value)) if value else bytes(size)
            reg[pos:pos + len(blob)] = blob
        elif kind == "bool":
            reg[pos] = 1 if value else 0
        elif kind.startswith("enum:"):
            struct.pack_into("<i", reg, pos, enum_value(kind[5:], value, 0))


# ── 记录 / 区域 ───────────────────────────────────────────────────────────

def decode_region(region: bytes, systems_count: int, name: str = "",
                  max_emitting: float = -1.0,
                  lay: Optional[_Layout] = None) -> Dict[str, Any]:
    """把一条 EffectPrototype 的变长区域解码为结构化 dict。

    ``lay`` 指定布局档案（默认取当前线程的服务器类型）。
    """
    lay = lay or current_layout()
    if systems_count < 0 or systems_count * lay.system_size > len(region):
        raise FxFormatError(
            f"systemsCount={systems_count} 超出区域范围（区域 {len(region)} 字节，"
            f"布局 {lay.key} 每条 {lay.system_size:#x} 字节）")
    ctx = _Ctx(region, lay)
    root: Dict[str, Any] = {
        "_type": "EffectPrototype",
        "_layout": lay.key,
        "name": name,
        "maxEmittingDuration": max_emitting,
        "systemsCount": systems_count,
        "regionSize": len(region),
        "systems": [],
        "raw": [],
    }

    for i in range(systems_count):
        base = i * lay.system_size
        sys: Dict[str, Any] = {"index": i}

        renderer: Dict[str, Any] = {}
        _decode_fields(ctx, base + SYS_RENDERER, lay.renderer_fields, renderer)
        sys["renderer"] = renderer

        emitter: Dict[str, Any] = {}
        _decode_fields(ctx, base + lay.sys_emitter, lay.emitter_generators, emitter)
        _decode_fields(ctx, base + lay.sys_emitter, lay.emitter_fields, emitter)
        sys["emitter"] = emitter

        animation: Dict[str, Any] = {}
        _decode_fields(ctx, base + lay.sys_animation, lay.animation_fields, animation)
        sys["animation"] = animation

        general: Dict[str, Any] = {}
        _decode_fields(ctx, base + lay.sys_general, lay.general_fields, general)
        sys["general"] = general

        for tag, off in (("distance", lay.sys_distance), ("scaler", lay.sys_scaler)):
            if not off:
                continue
            node: Dict[str, Any] = {}
            _decode_fields(ctx, base + off, lay.distance_fields, node)
            node["configs"] = _decode_configs(ctx, base + off + 4, base + off, tag,
                                              with_capacity=False)
            sys[tag] = node

        sys["name"] = _decode_string(ctx, base + lay.sys_name, "name")

        inten: Dict[str, Any] = {}
        inode, iat = _array_body(ctx, base + lay.sys_intensities,
                                 base + lay.sys_intensities, 0x10, "intensities")
        inten.update(inode)
        inten["items"] = []
        if iat:
            for i in range(inten["count"]):
                pos = iat + i * 0x10
                cfg, cat = _array_body(ctx, pos, pos, CONFIG_SIZE, f"intensity[{i}]")
                item: Dict[str, Any] = {"configs": cfg}
                if cat:
                    try:
                        cfg["items"] = [
                            _decode_config(ctx, cat + k * CONFIG_SIZE,
                                           f"intensity[{i}][{k}]")
                            for k in range(cfg["count"])]
                    except FxFormatError:
                        cfg["items"] = []
                inten["items"].append(item)
        sys["intensities"] = inten

        _decode_components(ctx, base, sys, lay)
        root["systems"].append(sys)

    root["raw"] = _collect_raw(ctx)
    return root

def _collect_raw(ctx: _Ctx, chunk: int = 256) -> List[Dict[str, Any]]:
    """把未被语义字段覆盖的字节按连续段收集成 ``[{"at", "hex"}]``。

    这些字节只用于回写保真（``encode_region`` 会原样写回），明文渲染时**不输出**。
    """
    data, cover = ctx.data, ctx.cover
    out: List[Dict[str, Any]] = []
    i = 0
    while i < len(data):
        if cover[i]:
            i += 1
            continue
        j = i
        while j < len(data) and not cover[j] and j - i < chunk:
            j += 1
        out.append({"at": i, "hex": data[i:j].hex()})
        i = j
    return out


def encode_region(root: Dict[str, Any]) -> bytes:
    """把 :func:`decode_region` 的 dict 编码回区域字节。

    布局档案取自 ``root["_layout"]``（缺失时退回当前线程的服务器类型）。
    """
    lay = LAYOUTS.get(str(root.get("_layout") or ""), None) or current_layout()
    size = int(root.get("regionSize") or 0)
    if size <= 0:
        raise FxFormatError("缺少 regionSize")
    systems = root.get("systems") or []
    count = int(root.get("systemsCount") or len(systems))
    if count * lay.system_size > size:
        raise FxFormatError("systemsCount 与 regionSize 不匹配")
    reg = bytearray(size)

    for raw in root.get("raw") or []:
        off = int(raw.get("at") or 0)
        blob = bytes.fromhex("".join(str(raw.get("hex") or "").split()))
        if off < 0 or off + len(blob) > size:
            raise FxFormatError(f"raw 越界: at=0x{off:X} len={len(blob)}")
        reg[off:off + len(blob)] = blob

    for i, sys in enumerate(systems):
        base = i * lay.system_size
        if isinstance(sys.get("renderer"), dict):
            _encode_fields(reg, base + SYS_RENDERER, lay.renderer_fields,
                           sys["renderer"], lay)
        if isinstance(sys.get("emitter"), dict):
            _encode_fields(reg, base + lay.sys_emitter, lay.emitter_generators,
                           sys["emitter"], lay)
            _encode_fields(reg, base + lay.sys_emitter, lay.emitter_fields,
                           sys["emitter"], lay)
        if isinstance(sys.get("animation"), dict):
            _encode_fields(reg, base + lay.sys_animation, lay.animation_fields,
                           sys["animation"], lay)
        if isinstance(sys.get("general"), dict):
            _encode_fields(reg, base + lay.sys_general, lay.general_fields,
                           sys["general"], lay)

        for tag, off in (("distance", lay.sys_distance), ("scaler", lay.sys_scaler)):
            if not off:
                continue
            node = sys.get(tag)
            if not isinstance(node, dict):
                continue
            _encode_fields(reg, base + off, lay.distance_fields, node, lay)
            _encode_configs(reg, base + off + 4, node.get("configs") or {}, base + off,
                            with_capacity=False, value_first=lay.ramp_value_first)

        name = sys.get("name")
        if isinstance(name, dict):
            _encode_string(reg, name, base + lay.sys_name)

        inten = sys.get("intensities")
        if isinstance(inten, dict):
            _encode_array_header(reg, base + lay.sys_intensities, inten,
                                 base + lay.sys_intensities,
                                 len(inten.get("items") or []) or int(inten.get("count") or 0))
            iat = int(inten.get("at") or 0)
            for i, item in enumerate(inten.get("items") or []):
                cfg = (item or {}).get("configs")
                if not isinstance(cfg, dict) or not iat:
                    continue
                pos = iat + i * 0x10
                _encode_configs(reg, pos, cfg, pos, value_first=lay.ramp_value_first)

        _encode_components(reg, base, sys.get("components"), lay)

    return bytes(reg)


def decode_effect_data(data: bytes, name: str = "",
                       lay: Optional[_Layout] = None) -> Dict[str, Any]:
    """解码 ``data``（从记录起点开始、延伸到 blob 末尾的切片）。"""
    if len(data) < RECORD_SIZE:
        raise FxFormatError(f"EffectPrototype 数据过短: {len(data)}")
    lay = lay or current_layout()
    max_emitting = _f32(data, 0x00)
    count = _u32(data, 0x04)
    rel = _i64(data, 0x08)
    start = rel
    end = len(data)
    if len(data) >= RECORD_SIZE * 2:
        nrel = _i64(data, RECORD_SIZE + 8)
        if nrel > rel:
            # 下一条记录的 rel 以**那条记录自身地址**为基准
            end = RECORD_SIZE + nrel
    if not (0 <= start <= end <= len(data)):
        raise FxFormatError(f"systems 区域异常: [0x{start:X}, 0x{end:X}) len=0x{len(data):X}")
    return decode_region(data[start:end], count, name, max_emitting, lay)


def record_region_bounds(db, record_index: int) -> Tuple[bytes, int, int]:
    """返回 (blob 字节, 区域起始, 区域结束)（EffectPrototype 数据块）。"""
    entry = None
    for e in db.databases:
        if e.prototype_magic == 0xEB23E0AF:
            entry = e
            break
    if entry is None:
        raise FxFormatError("assets.bin 中没有 EffectPrototype 数据块")
    blob = entry.data
    if record_index < 0 or record_index >= entry.record_count:
        raise FxFormatError(f"记录索引越界: {record_index}")
    rec_addr = BLOB_HEADER + record_index * RECORD_SIZE
    rel = _i64(blob, rec_addr + 8)
    start = rec_addr + rel
    if record_index + 1 < entry.record_count:
        nrel = _i64(blob, rec_addr + RECORD_SIZE + 8)
        end = rec_addr + RECORD_SIZE + nrel
    else:
        end = len(blob)
    if not (rec_addr <= start <= end <= len(blob)):
        raise FxFormatError(f"区域范围异常: [0x{start:X}, 0x{end:X})")
    return blob, start, end


# ── EffectMetadataPrototype（粒子 `/xxx.xml/shared` 元数据）────────────────
#
# 布局来自 26.11PT1 的 ``FUN_1406daa00``（类型 unpack 入口）→
# ``FUN_1406e18a0``（数组校验）→ ``FUN_1406e6850``（逐条）→
# ``FUN_1406f3d30``（单条 intensitiesMetadata）：
#
# * 记录（16 字节）::
#
#       +0x00  u32  count
#       +0x04  u32  pad
#       +0x08  i64  rel（**基准 = 本记录起点**）
#       +0x10  下一条记录
#
# * 元素 0x20 字节::
#
#       +0x00  String intensityName（size/capacity/rel，基准 = 字段自身）
#       +0x10  f32    minIntensity
#       +0x14  f32    maxIntensity
#       +0x18  f32    defaultIntensity
#       +0x1C  u32    未知（26.10 / 26.11 数据中恒为 0，原样保留）
#
# 与 EffectPrototype 一致：区域只含数组 + 字符串池（``rel`` 起算），
# 记录头里的 count/rel 单独保存，长度按本记录实际内容算出。

#: EffectMetadataPrototype 记录长度
METADATA_RECORD_SIZE = 0x10
#: intensitiesMetadata 单条长度
METADATA_ITEM_SIZE = 0x20

#: intensitiesMetadata 元素字段（String 之外的部分）
METADATA_ITEM_FIELDS: Tuple[Tuple[str, int, str], ...] = (
    ("minIntensity", 0x10, "f32"),
    ("maxIntensity", 0x14, "f32"),
    ("defaultIntensity", 0x18, "f32"),
    ("unknown", 0x1C, "u32"),
)


def decode_metadata_region(region: bytes, count: int = 0,
                           name: str = "") -> Dict[str, Any]:
    """把一条 EffectMetadataPrototype 的数组区（元素 + 字符串池）解码为 dict。"""
    ctx = _Ctx(region)
    root: Dict[str, Any] = {
        "_type": "EffectMetadataPrototype",
        "name": name,
        "count": count,
        "regionSize": len(region),
        "intensities": [],
        "raw": [],
    }
    if count and count * METADATA_ITEM_SIZE > len(region):
        root["invalid"] = True
        count = 0
    for i in range(count):
        pos = i * METADATA_ITEM_SIZE
        item: Dict[str, Any] = {"index": i}
        item["name"] = _decode_string(ctx, pos, "intensityName")
        _decode_fields(ctx, pos, METADATA_ITEM_FIELDS, item)
        root["intensities"].append(item)
    root["raw"] = _collect_raw(ctx)
    return root


def encode_metadata_region(root: Dict[str, Any]) -> bytes:
    """把 :func:`decode_metadata_region` 的 dict 编码回数组区字节。"""
    size = int(root.get("regionSize") or 0)
    if size <= 0:
        return b""
    reg = bytearray(size)
    for raw in root.get("raw") or []:
        off = int(raw.get("at") or 0)
        blob = bytes.fromhex("".join(str(raw.get("hex") or "").split()))
        if off < 0 or off + len(blob) > size:
            raise FxFormatError(f"raw 越界: at=0x{off:X} len={len(blob)}")
        reg[off:off + len(blob)] = blob
    for i, item in enumerate(root.get("intensities") or []):
        pos = i * METADATA_ITEM_SIZE
        name = item.get("name")
        if isinstance(name, dict):
            _encode_string(reg, name, pos)
        _encode_fields(reg, pos, METADATA_ITEM_FIELDS, item)
    return bytes(reg)


def decode_metadata_data(data: bytes, name: str = "") -> Dict[str, Any]:
    """解码 ``data``（从记录起点开始、延伸到 blob 末尾的切片）。

    记录头 ``{u32 count; u32 pad; i64 rel}`` 里的 ``rel`` 指向元素数组
    （基准 = 本记录起点）；区域 = 数组 + 紧随其后的字符串池，长度按本记录
    实际内容算出，因此最后一条记录也不会把 blob 其它部分当成 raw。
    """
    if len(data) < METADATA_RECORD_SIZE:
        raise FxFormatError(f"EffectMetadataPrototype 数据过短: {len(data)}")
    count = _u32(data, 0x00)
    rel = _i64(data, 0x08)
    if not count or rel <= 0:
        return decode_metadata_region(b"", 0, name)
    end = _metadata_span(data, count, rel)
    if not (METADATA_RECORD_SIZE <= rel <= end <= len(data)):
        raise FxFormatError(
            f"metadata 区域异常: [0x{rel:X}, 0x{end:X}) len=0x{len(data):X}")
    return decode_metadata_region(data[rel:end], count, name)


def _metadata_span(data: bytes, count: int, rel: int) -> int:
    """本记录数组区结束偏移 = 元素数组 + 字符串池（越界时退回数据长度）。"""
    need = rel + count * METADATA_ITEM_SIZE
    for i in range(min(count, 0x4000)):
        pos = rel + i * METADATA_ITEM_SIZE
        if pos + 16 > len(data):
            return len(data)
        size = _u32(data, pos)
        if size and size <= 0x10000:
            stop = pos + _i64(data, pos + 8) + size
            if stop > need:
                need = stop
    return need if need <= len(data) else len(data)


# ── XML 渲染 ──────────────────────────────────────────────────────────────

def _fmt_f(x: Any) -> str:
    v = float(x)
    if v != v:
        return "nan"
    if v == float("inf"):
        return "inf"
    if v == float("-inf"):
        return "-inf"
    return repr(v)


def _xml_escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _attrs(pairs: Iterable[Tuple[str, Any]]) -> str:
    return "".join(f' {k}="{_xml_escape(str(v))}"' for k, v in pairs if v is not None)


def _write_value(lines: List[str], key: str, value: Any, indent: int) -> None:
    pad = "  " * indent
    if isinstance(value, bool):
        lines.append(f"{pad}<{key}>{'true' if value else 'false'}</{key}>")
    elif isinstance(value, (int, float)):
        lines.append(f"{pad}<{key}>{_fmt_f(value) if isinstance(value, float) else value}</{key}>")
    elif isinstance(value, str):
        lines.append(f"{pad}<{key}>{_xml_escape(value)}</{key}>")
    elif isinstance(value, dict):
        if "x" in value or "y" in value or "z" in value:
            pairs = [("x", _fmt_f(value.get("x", 0.0))),
                     ("y", _fmt_f(value.get("y", 0.0))),
                     ("z", _fmt_f(value.get("z", 0.0)))]
            if "w" in value:
                pairs.append(("w", _fmt_f(value.get("w", 0.0))))
            lines.append(f"{pad}<{key}" + _attrs(pairs) + "/>")
            return
        attrs: List[Tuple[str, Any]] = []
        if "at" in value:
            attrs.append(("at", f"0x{int(value['at']):X}"))
        for k in ("size", "capacity", "rel", "type", "count", "action",
                  "parameterType", "samplingType"):
            if k in value:
                attrs.append((k, value[k]))
        text = value.get("text")
        if text is not None:
            lines.append(f"{pad}<{key}{_attrs(attrs)}>{_xml_escape(str(text))}</{key}>")
            return
        lines.append(f"{pad}<{key}{_attrs(attrs)}>")
        for k, v in value.items():
            if k.startswith("_") or k in ("at", "size", "capacity", "rel", "type", "count",
                                          "action", "parameterType", "samplingType", "text"):
                continue
            if k == "points":
                for pt in v or []:
                    color = pt.get("color")
                    if isinstance(color, dict):
                        lines.append(f"{pad}  <point" + _attrs((
                            ("time", _fmt_f(pt.get("time", 0.0))),
                            ("r", _fmt_f(color.get("x", 0.0))),
                            ("g", _fmt_f(color.get("y", 0.0))),
                            ("b", _fmt_f(color.get("z", 0.0))),
                            ("a", _fmt_f(color.get("w", 0.0))),
                        )) + "/>")
                    else:
                        lines.append(f"{pad}  <point" + _attrs((
                            ("time", _fmt_f(pt.get("time", 0.0))),
                            ("value", _fmt_f(pt.get("value", 0.0))),
                        )) + "/>")
            elif k == "prototypes":
                for item in v or []:
                    _write_value(lines, "item", item, indent + 1)
            elif k == "values":
                for val in v or []:
                    lines.append(f"{pad}  <flag>{val}</flag>")
            elif k == "items":
                tag = "config" if "ramp" in value or "flags" in value else "item"
                for item in v or []:
                    _write_value(lines, tag, item, indent + 1)
            else:
                _write_value(lines, k, v, indent + 1)
        lines.append(f"{pad}</{key}>")
    elif isinstance(value, list):
        for item in value:
            _write_value(lines, "item", item, indent)


def format_metadata_text(decoded: Dict[str, Any]) -> str:
    """EffectMetadataPrototype 解码结果 → 可读 XML（粒子 `/xxx.xml/shared`）。"""
    if not isinstance(decoded, dict) or decoded.get("_type") != "EffectMetadataPrototype":
        raise FxFormatError("需要 EffectMetadataPrototype 解码结果")
    root_attrs: List[Tuple[str, Any]] = []
    if decoded.get("name"):
        root_attrs.append(("name", decoded["name"]))
    root_attrs.append(("count", decoded.get("count", 0)))
    root_attrs.append(("regionSize", decoded.get("regionSize", 0)))
    lines: List[str] = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<!-- 由 assets.bin 明文转码生成：结构字段均已解码；'
        '数据池里无字段引用的对齐/空闲字节不在此显示，但仍参与无损回写 -->',
        f"<effectMetadata{_attrs(root_attrs)}>",
    ]
    for item in decoded.get("intensities") or []:
        name = item.get("name") or {}
        attrs: List[Tuple[str, Any]] = [
            ("name", name.get("text") or ""),
            ("min", _fmt_f(item.get("minIntensity", 0.0))),
            ("max", _fmt_f(item.get("maxIntensity", 0.0))),
            ("default", _fmt_f(item.get("defaultIntensity", 0.0))),
        ]
        if item.get("unknown"):
            attrs.append(("unknown", item["unknown"]))
        if name.get("at") is not None:
            attrs.append(("at", f"0x{int(name['at']):X}"))
        lines.append("  <intensity" + _attrs(attrs) + "/>")
    # 数据池里无字段引用的对齐/空闲字节只参与回写，不在明文里显示
    lines.append("</effectMetadata>")
    return "\n".join(lines) + "\n"


def format_effect_text(decoded: Dict[str, Any]) -> str:
    """结构化解码结果 → **带偏移的结构视图** XML（调试用，不含合并逻辑）。

    导出给用户看的明文用 :func:`format_particle_text`（对齐游戏自带粒子 XML）。
    """
    if not isinstance(decoded, dict):
        raise FxFormatError("需要解码结果 dict")
    if decoded.get("_type") == "EffectMetadataPrototype":
        return format_metadata_text(decoded)
    if decoded.get("_type") != "EffectPrototype":
        raise FxFormatError("需要 EffectPrototype 解码结果")
    lines: List[str] = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<!-- 由 assets.bin 明文转码生成：结构字段均已解码；'
        '数据池里无字段引用的对齐/空闲字节不在此显示，但仍参与无损回写 -->',
    ]
    root_attrs: List[Tuple[str, Any]] = []
    if decoded.get("name"):
        root_attrs.append(("name", decoded["name"]))
    root_attrs.append(("maxEmittingDuration", _fmt_f(decoded.get("maxEmittingDuration", -1.0))))
    root_attrs.append(("systemsCount", decoded.get("systemsCount", 0)))
    root_attrs.append(("regionSize", decoded.get("regionSize", 0)))
    lines.append(f"<effect{_attrs(root_attrs)}>")

    for sys in decoded.get("systems") or []:
        lines.append(f'  <system index="{sys.get("index", 0)}">')
        for tag in ("renderer", "emitter", "animation", "general", "distance", "scaler"):
            node = sys.get(tag)
            if not isinstance(node, dict):
                continue
            lines.append(f"    <{tag}>")
            for key, value in node.items():
                if key in ("configsCount", "configsAt"):
                    continue
                _write_value(lines, key, value, 3)
            lines.append(f"    </{tag}>")

        name = sys.get("name")
        if isinstance(name, dict):
            if name.get("size"):
                lines.append("    <name" + _attrs((
                    ("at", f"0x{int(name['at']):X}"), ("size", name["size"]))) +
                    f">{_xml_escape(str(name.get('text') or ''))}</name>")
            else:
                lines.append("    <name/>")

        inten = sys.get("intensities")
        if isinstance(inten, dict):
            attrs = [("count", inten.get("count", 0))]
            if inten.get("at") is not None:
                attrs.append(("at", f"0x{int(inten['at']):X}"))
            items = inten.get("items") or []
            if not items:
                lines.append(f"    <intensities{_attrs(attrs)}/>")
            else:
                lines.append(f"    <intensities{_attrs(attrs)}>")
                for k, item in enumerate(items):
                    lines.append(f'      <intensity index="{k}">')
                    for key, value in (item or {}).items():
                        _write_value(lines, key, value, 4)
                    lines.append("      </intensity>")
                lines.append("    </intensities>")

        comps = sys.get("components")
        if isinstance(comps, dict):
            attrs = [("count", comps.get("count", 0))]
            if comps.get("at") is not None:
                attrs.append(("at", f"0x{int(comps['at']):X}"))
            lines.append(f"    <components{_attrs(attrs)}>")
            for item in comps.get("items") or []:
                head = ("      <component" + _attrs((
                    ("type", item.get("type")),
                    ("action", item.get("action")),
                    ("kind", item.get("kind")),
                    ("at", f"0x{int(item['at']):X}" if item.get("at") is not None else None),
                    ("fieldsAt", (f"0x{int(item['fieldsAt']):X}"
                                  if item.get("fieldsAt") is not None else None)),
                )))
                body = [v for v in (item.get("fields"), item.get("localLight"),
                                    item.get("decal")) if isinstance(v, dict) and v]
                if not body:
                    lines.append(head + "/>")
                    continue
                lines.append(head + ">")
                for node in body:
                    for key, value in node.items():
                        _write_value(lines, key, value, 4)
                lines.append("      </component>")
            lines.append("    </components>")
        lines.append("  </system>")

    # 数据池里无字段引用的对齐/空闲字节只参与回写，不在明文里显示
    lines.append("</effect>")
    return "\n".join(lines) + "\n"


# ── 游戏原始粒子 XML（high / low / shared 合一份）────────────────────────────
#
# 目标格式对齐 Korebli 自带的粒子明文（例如
# ``res_unpack/helpers/particles/sfx_fail.xml``）：制表符缩进、标量包在
# ``\t`` 之间、浮点固定 4 位小数、向量用空格分隔、点写成 ``<value>`` + ``<time>``、
# 生成器用 ``<type>`` + ``<data>``、组件用 ``<type>`` + ``<data>`` 双层。

#: 粒子文件的分区名（顺序即输出顺序）
PARTICLE_PARTS: Tuple[str, ...] = ("high", "low", "shared")

_T = "\t"


def _gnum(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    v = float(value)
    if v != v:
        return "nan"
    if v == float("inf"):
        return "inf"
    if v == float("-inf"):
        return "-inf"
    return f"{v:.4f}"


def _gline(lines: List[str], depth: int, tag: str, value: Any) -> None:
    text = value if isinstance(value, str) else _gnum(value)
    if text == "":
        lines.append(f"{_T * depth}<{tag} />")
    else:
        lines.append(f"{_T * depth}<{tag}>{_T}{_xml_escape(str(text))}{_T}</{tag}>")


def _gvec(lines: List[str], depth: int, tag: str, vec: Dict[str, Any],
          size: int = 3) -> None:
    keys = ("x", "y", "z", "w")[:size]
    text = " ".join(_gnum(vec.get(k, 0.0)) for k in keys)
    lines.append(f"{_T * depth}<{tag}>{_T}{text}{_T}</{tag}>")


def _gstring(lines: List[str], depth: int, tag: str, node: Dict[str, Any]) -> None:
    text = str(node.get("text") or "")
    size = int(node.get("size") or (len(text) + 1))
    lines.append(f"{_T * depth}<{tag}>")
    _gline(lines, depth + 1, "size", size)
    if text:
        lines.append(f"{_T * (depth + 1)}<text>{_T}{_xml_escape(text)}{_T}</text>")
    else:
        lines.append(f"{_T * (depth + 1)}<text />")
    lines.append(f"{_T * depth}</{tag}>")


def _gpoints(lines: List[str], depth: int, tag: str, node: Dict[str, Any]) -> None:
    """``<tag>`` + ``<count>`` + ``<points>``（元素 ``<value>`` 再 ``<time>``）。"""
    points = [p for p in (node.get("points") or []) if isinstance(p, dict)]
    lines.append(f"{_T * depth}<{tag}>")
    _gline(lines, depth + 1, "count", len(points) or int(node.get("count") or 0))
    if points:
        lines.append(f"{_T * (depth + 1)}<points>")
        for p in points:
            lines.append(f"{_T * (depth + 2)}<item>")
            color = p.get("color")
            if isinstance(color, dict):
                _gvec(lines, depth + 3, "value", color, 4)
            else:
                _gline(lines, depth + 3, "value", p.get("value", 0.0))
            _gline(lines, depth + 3, "time", p.get("time", 0.0))
            lines.append(f"{_T * (depth + 2)}</item>")
        lines.append(f"{_T * (depth + 1)}</points>")
    lines.append(f"{_T * depth}</{tag}>")


def _gvalues(lines: List[str], depth: int, tag: str, node: Dict[str, Any]) -> None:
    """``<tag>`` + ``<count>`` + ``<values><item>``（强度标志位等整数数组）。"""
    values = list(node.get("values") or [])
    lines.append(f"{_T * depth}<{tag}>")
    _gline(lines, depth + 1, "count", len(values) or int(node.get("count") or 0))
    if values:
        lines.append(f"{_T * (depth + 1)}<values>")
        for v in values:
            _gline(lines, depth + 2, "item", int(v))
        lines.append(f"{_T * (depth + 1)}</values>")
    lines.append(f"{_T * depth}</{tag}>")


def _gcounted_configs(lines: List[str], depth: int, node: Dict[str, Any]) -> None:
    """``<configsCount>`` + （非空时）``<configs><item>``；每项 = ramp 曲线 + flags。"""
    items = [it for it in (node.get("items") or []) if isinstance(it, dict)]
    _gline(lines, depth, "configsCount", len(items) or int(node.get("count") or 0))
    if not items:
        return
    lines.append(f"{_T * depth}<configs>")
    for item in items:
        lines.append(f"{_T * (depth + 1)}<item>")
        _gpoints(lines, depth + 2, "ramp", item.get("ramp") or {})
        _gvalues(lines, depth + 2, "flags", item.get("flags") or {})
        lines.append(f"{_T * (depth + 1)}</item>")
    lines.append(f"{_T * depth}</configs>")


def _gvaluegen(lines: List[str], depth: int, tag: str, node: Dict[str, Any]) -> None:
    kind = str(node.get("type") or "")
    lines.append(f"{_T * depth}<{tag}>")
    _gline(lines, depth + 1, "type", kind)
    data_depth = depth + 1
    if kind.endswith("RAMP"):
        ramp = node.get("ramp") if isinstance(node.get("ramp"), dict) else {}
        lines.append(f"{_T * data_depth}<data>")
        _gpoints(lines, data_depth + 1, "ramp", ramp)
        _gline(lines, data_depth + 1, "parameterType", str(ramp.get("parameterType") or ""))
        _gline(lines, data_depth + 1, "samplingType", str(ramp.get("samplingType") or ""))
        lines.append(f"{_T * data_depth}</data>")
    elif kind.endswith("CONSTANT"):
        lines.append(f"{_T * data_depth}<data>")
        _gline(lines, data_depth + 1, "value", node.get("value", 0.0))
        lines.append(f"{_T * data_depth}</data>")
    elif (kind.endswith("RANDOM") or kind.endswith("CUMULATIVE")
            or kind.endswith("LINEAR")):
        lines.append(f"{_T * data_depth}<data>")
        _gline(lines, data_depth + 1, "from", node.get("from", 0.0))
        _gline(lines, data_depth + 1, "to", node.get("to", 0.0))
        lines.append(f"{_T * data_depth}</data>")
    lines.append(f"{_T * depth}</{tag}>")


def _gvectgen(lines: List[str], depth: int, tag: str, node: Dict[str, Any]) -> None:
    protos = [p for p in (node.get("prototypes") or []) if isinstance(p, dict)]
    lines.append(f"{_T * depth}<{tag}>")
    _gline(lines, depth + 1, "type", str(node.get("type") or ""))
    _gline(lines, depth + 1, "count", len(protos) or int(node.get("count") or 0))
    if protos:
        lines.append(f"{_T * (depth + 1)}<prototypes>")
        for proto in protos:
            lines.append(f"{_T * (depth + 2)}<item>")
            _gline(lines, depth + 3, "type", str(proto.get("type") or ""))
            lines.append(f"{_T * (depth + 3)}<data>")
            for key, size in (("point", 3), ("center", 3), ("from", 3), ("to", 3),
                              ("corner", 3), ("opposite", 3), ("basisU", 3),
                              ("basisV", 3), ("difference", 3)):
                vec = proto.get(key)
                if isinstance(vec, dict):
                    _gvec(lines, depth + 4, key, vec, size)
            for key in ("radius", "maxRadius", "minRadius", "scale"):
                if isinstance(proto.get(key), (int, float)):
                    _gline(lines, depth + 4, key, proto[key])
            lines.append(f"{_T * (depth + 3)}</data>")
            lines.append(f"{_T * (depth + 2)}</item>")
        lines.append(f"{_T * (depth + 1)}</prototypes>")
    lines.append(f"{_T * depth}</{tag}>")


def _gfield(lines: List[str], depth: int, key: str, value: Any) -> None:
    """按字段形状分派（标量 / 向量 / 曲线 / 数组 / 生成器 / 字符串）。"""
    if isinstance(value, bool) or isinstance(value, (int, float)):
        _gline(lines, depth, key, value)
        return
    if isinstance(value, str):
        _gline(lines, depth, key, value)
        return
    if not isinstance(value, dict):
        return
    if "x" in value:
        size = 4 if "w" in value else (3 if "z" in value else 2)
        _gvec(lines, depth, key, value, size)
    elif "points" in value:
        _gpoints(lines, depth, key, value)
    elif "values" in value:
        _gvalues(lines, depth, key, value)
    elif "prototypes" in value:
        _gvectgen(lines, depth, key, value)
    elif "configs" in value:
        _gconfigs(lines, depth, key, value.get("configs") or {})
    elif "type" in value:
        _gvaluegen(lines, depth, key, value)
    elif "text" in value or "size" in value:
        _gstring(lines, depth, key, value)


def _gsystem(lines: List[str], depth: int, sys: Dict[str, Any]) -> None:
    for tag in ("renderer", "emitter", "general"):
        node = sys.get(tag)
        if isinstance(node, dict):
            lines.append(f"{_T * depth}<{tag}>")
            for key, value in node.items():
                if key.startswith("_"):
                    continue
                _gfield(lines, depth + 1, key, value)
            lines.append(f"{_T * depth}</{tag}>")

    dist = sys.get("distance")
    if isinstance(dist, dict):
        lines.append(f"{_T * depth}<distance>")
        _gline(lines, depth + 1, "maxDistance", dist.get("maxDistance", 0.0))
        _gcounted_configs(lines, depth + 1, dist.get("configs") or {})
        lines.append(f"{_T * depth}</distance>")

    name = sys.get("name")
    if isinstance(name, dict):
        _gstring(lines, depth, "name", name)

    anim = sys.get("animation")
    if isinstance(anim, dict):
        lines.append(f"{_T * depth}<animation>")
        for key, value in anim.items():
            if key.startswith("_"):
                continue
            _gfield(lines, depth + 1, key, value)
        lines.append(f"{_T * depth}</animation>")

    comps = sys.get("components") or {}
    items = [it for it in (comps.get("items") or []) if isinstance(it, dict)]
    _gline(lines, depth, "componentsCount", len(items) or int(comps.get("count") or 0))
    if items:
        lines.append(f"{_T * depth}<components>")
        for item in items:
            lines.append(f"{_T * (depth + 1)}<item>")
            _gline(lines, depth + 2, "type", str(item.get("type") or ""))
            fields = item.get("fields")
            if isinstance(fields, dict) and fields:
                lines.append(f"{_T * (depth + 2)}<data>")
                _gline(lines, depth + 3, "type", str(item.get("action") or ""))
                lines.append(f"{_T * (depth + 3)}<data>")
                for key, value in fields.items():
                    if key.startswith("_"):
                        continue
                    _gfield(lines, depth + 4, key, value)
                lines.append(f"{_T * (depth + 3)}</data>")
                lines.append(f"{_T * (depth + 2)}</data>")
            else:
                body = item.get("localLight") or item.get("decal")
                if isinstance(body, dict) and body:
                    lines.append(f"{_T * (depth + 2)}<data>")
                    for key, value in body.items():
                        if key.startswith("_"):
                            continue
                        _gfield(lines, depth + 3, key, value)
                    lines.append(f"{_T * (depth + 2)}</data>")
            lines.append(f"{_T * (depth + 1)}</item>")
        lines.append(f"{_T * depth}</components>")

    inten = sys.get("intensities")
    if isinstance(inten, dict):
        channels = [it for it in (inten.get("items") or []) if isinstance(it, dict)]
        lines.append(f"{_T * depth}<intensities>")
        _gline(lines, depth + 1, "channelCount",
               len(channels) or int(inten.get("count") or 0))
        if channels:
            lines.append(f"{_T * (depth + 1)}<channels>")
            for chan in channels:
                lines.append(f"{_T * (depth + 2)}<item>")
                _gcounted_configs(lines, depth + 3, (chan or {}).get("configs") or {})
                lines.append(f"{_T * (depth + 2)}</item>")
            lines.append(f"{_T * (depth + 1)}</channels>")
        lines.append(f"{_T * depth}</intensities>")

    scaler = sys.get("scaler")
    if isinstance(scaler, dict):
        lines.append(f"{_T * depth}<scaler>")
        _gcounted_configs(lines, depth + 1, scaler.get("configs") or {})
        _gline(lines, depth + 1, "maxScale", scaler.get("maxDistance", 0.0))
        lines.append(f"{_T * depth}</scaler>")


def _gprototype(lines: List[str], depth: int, root: Dict[str, Any]) -> None:
    lines.append(f"{_T * depth}<prototype>")
    _gline(lines, depth + 1, "systemsCount", int(root.get("systemsCount") or 0))
    systems = [s for s in (root.get("systems") or []) if isinstance(s, dict)]
    if systems:
        lines.append(f"{_T * (depth + 1)}<systems>")
        for sys in systems:
            lines.append(f"{_T * (depth + 2)}<item>")
            _gsystem(lines, depth + 3, sys)
            lines.append(f"{_T * (depth + 2)}</item>")
        lines.append(f"{_T * (depth + 1)}</systems>")
    _gline(lines, depth + 1, "maxEmittingDuration", root.get("maxEmittingDuration", 0.0))
    lines.append(f"{_T * depth}</prototype>")


def _gmetadata(lines: List[str], depth: int, root: Dict[str, Any]) -> None:
    items = [it for it in (root.get("intensities") or []) if isinstance(it, dict)]
    lines.append(f"{_T * depth}<prototype>")
    _gline(lines, depth + 1, "intensitiesCount", len(items) or int(root.get("count") or 0))
    if items:
        lines.append(f"{_T * (depth + 1)}<intensitiesMetadata>")
        for item in items:
            lines.append(f"{_T * (depth + 2)}<item>")
            _gstring(lines, depth + 3, "intensityName", item.get("name") or {})
            _gline(lines, depth + 3, "minIntensity", item.get("minIntensity", 0.0))
            _gline(lines, depth + 3, "maxIntensity", item.get("maxIntensity", 0.0))
            _gline(lines, depth + 3, "defaultIntensity", item.get("defaultIntensity", 0.0))
            lines.append(f"{_T * (depth + 2)}</item>")
        lines.append(f"{_T * (depth + 1)}</intensitiesMetadata>")
    lines.append(f"{_T * depth}</prototype>")


def _root_tag(file_name: str) -> str:
    """根节点名 = 粒子文件名（非法 XML 名时退回 ``particle``）。"""
    name = (file_name or "effect.xml").strip()
    if not name or not (name[0].isalpha() or name[0] == "_"):
        return "particle"
    for ch in name:
        if not (ch.isalnum() or ch in "._-:"):
            return "particle"
    return name


def format_particle_text(parts: Dict[str, Any], file_name: str = "effect.xml") -> str:
    """把同一粒子文件的 ``high`` / ``low`` / ``shared`` 合成一份游戏格式 XML。

    :param parts: ``{"high": 解码结果, "low": …, "shared": …}``，缺哪个就不输出哪个
    :param file_name: 粒子文件名（``SignalFlare.xml``），用作根节点名
    """
    root = _root_tag(file_name)
    lines: List[str] = [f"<{root}>"]
    emitted = 0
    for part in PARTICLE_PARTS:
        node = parts.get(part)
        if not isinstance(node, dict):
            continue
        lines.append(f"{_T}<{part}>")
        if part == "shared":
            _gmetadata(lines, 2, node)
        else:
            _gprototype(lines, 2, node)
        lines.append(f"{_T}</{part}>")
        emitted += 1
    if not emitted:
        raise FxFormatError("没有可输出的粒子分区（high / low / shared）")
    lines.append(f"</{root}>")
    return "\n".join(lines) + "\n"
