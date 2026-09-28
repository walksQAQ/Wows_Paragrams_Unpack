/*
 * material.hlsl —— 实体材质着色器族（PBS / wire / unlit / INDEXED）
 *
 * 搬运原则（架构文档 §1.4）：**只换语言，不换算法**。
 * 本文件的公式与 `ui/geometry_renderer.py` 中已验证的 GLSL 逐行对应：
 *   FRAG_PBS (u_mode 0/1/2) 与 FRAG_INDEXED (u_mode 3)。
 * 参数命名遵循 §5.4.1：`_mg.R` → F0 混合权重（`mg.r` 仅作 F0 lerp 因子，**不是 metallic**）、
 * `_mg.G` → gloss（光照阶段取 roughness = 1 - gloss）、`_mg.B` → emissive 掩码。
 *
 * 与 GLSL 的差异仅限 API 层面：
 *   - gl_FragCoord/u_viewport → SV_POSITION 的像素坐标（语义等价，仅在 fullscreen 路径用到）
 *   - texture()/textureGrad() → Sample()/SampleGrad()
 *   - textureGather() → Gather()
 */

/* ============================ 常量缓冲 ============================ */

cbuffer FrameCB : register(b0)
{
    /* row_major：宿主传的是行主序数学矩阵（与旧 GLSL 的 GL_FALSE 语义等价），
     * 不加此修饰 HLSL 会按列主序解释 → 相当于转置 → 几何位置全错。 */
    row_major float4x4 g_mvp;          // proj * view；实例矩阵由 INST 属性提供
    row_major float4x4 g_normal_mat;   // 法线矩阵（单位阵；变换在 VS 里与实例矩阵合并）
    float4   g_light_dir;    // xyz = 光照方向
    float4   g_ambient;      // xyz = 环境光（保底，不随距离衰减）
    float4   g_light_pos;    // xyz = 点光源位置（天上）
    float4   g_view_dir;     // xyz = 观察方向（eye - target 归一化）
    float4   g_params;       // x=normal_strength y=opacity z=emissive_k w=emissive_on
    float4   g_params2;      // x=mode y=debug_mode z=instanced w=matid_vis
};

cbuffer MatCB : register(b1)
{
    float4 g_mat;            // x=has_tex y=has_normal z=has_mg w=gamma
};

/* INDEXED 逐材质数组（196 项；仅 INDEXED 家族绑定/更新） */
cbuffer IndexedCB : register(b2)
{
    float4 g_offset_scale[196];
    float4 g_rotation[196];
    float4 g_tile_idx[196];
    float4 g_tint[196];
    float4 g_remove[196];
};

/* ============================ 纹理与采样器 ============================ */

Texture2D        g_tex         : register(t0);   // diffuse / albedo
Texture2D        g_normal_map  : register(t1);   // normalMap（SPARSE 声明才有效）
Texture2D        g_mg_map      : register(t2);   // metallicGlossMap
Texture2D        g_matid_tex   : register(t3);   // INDEXED materialIdMap
Texture2DArray   g_tiles_tex   : register(t4);   // INDEXED albedoArray
Texture2DArray   g_normal_tex  : register(t5);   // INDEXED normalArray
Texture2DArray   g_mg_tex      : register(t6);   // INDEXED MGArray
Texture2D        g_art_tex     : register(t7);   // INDEXED artMap
Texture2DArray   g_noise_tex   : register(t8);   // INDEXED rgbNoiseMap
Texture2D        g_alpha_n_map : register(t9);   // INDEXED normalMap(_alpha_n)

/* ---- deferred 中间缓冲（P3/P5）：Pass1 写入，全屏 pass 读取 ---- */
Texture2D g_scene_tex        : register(t10);  // MRT0: 未打光 albedo(linear)，.a = F0 混合权重
Texture2D g_scene_normal_tex : register(t11);  // MRT1: 世界法线，.a = gloss（na/nb 共用）
Texture2D g_scene_final_tex  : register(t12);  // Hull+Decal 合成后的最终法线
Texture2D g_scene_world_tex  : register(t13);  // MRT2: 世界坐标

SamplerState g_smp       : register(s0);   // wrap + 线性 + mip（通用）
SamplerState g_smp_point : register(s1);   // point + clamp（materialIdMap）
SamplerState g_smp_nomip : register(s2);   // wrap + 线性（base level）

/* ── GL→D3D 采样校正（V 轴）────────────────────────────────────────
 * 旧渲染器把顶点 UV **原样**上传（`vdata[:,6:8]=uvs`），VS 里 `v_uv=in_uv` 不翻转；
 * 而 GL 的 t=0 在纹理**底边**、D3D 的 v=0 在**顶边** ⇒ 同一份 DDS 字节两边上下相反。
 * INDEXED 定版公式（材质ID 区域、artMap 覆盖区域、瓦片相位）都是在 GL 朝向下调出来的，
 * 因此只在**取纹理**时把 V 翻成 1-v，公式本身仍按 GL 空间书写；全屏 pass 用屏幕坐标
 * 取纹理，不经过本函数。
 * ⚠️ SampleGrad 的 ddx/ddy 仍用 GL 空间的导数（|d(1-v)| = |dv| ⇒ mip 选择不变）。
 */
float2 glUV(float2 uv)          { return float2(uv.x, 1.0 - uv.y); }
float3 glUV(float2 uv, float s) { return float3(uv.x, 1.0 - uv.y, s); }

/* ============================ 公共函数 ============================ */

/* 统一 PBR：Cook-Torrance GGX + Schlick Fresnel 直接光镜面反射（天上的点光源）。
 * ★ 与 GLSL 完全一致：无程序化天空盒环境反射；MG 不影响基础颜色。 */
float3 pbr_light(float3 albedo, float3 N, float f0_weight, float gloss, float3 lit, float3 worldPos)
{
    float3 path = g_light_pos.xyz - worldPos;
    float  dist = max(length(path), 1e-4);
    float3 L = path / dist;
    float  atten = clamp(1.0 / (1.0 + 0.0008 * dist * dist), 0.0, 1.0);
    float3 V = normalize(g_view_dir.xyz);
    float3 H = normalize(L + V);
    float  NdotL = max(dot(N, L), 0.0);
    float  NdotV = max(dot(N, V), 0.0);
    float  NdotH = max(dot(N, H), 0.0);
    float  VdotH = max(dot(V, H), 0.0);

    float  roughness = clamp(1.0 - gloss, 0.04, 1.0);
    float3 F0 = lerp(float3(0.04, 0.04, 0.04), albedo, f0_weight);
    float3 F  = F0 + (1.0 - F0) * pow(1.0 - VdotH, 5.0);
    float  a  = roughness * roughness;
    float  a2 = a * a;
    float  denom = NdotH * NdotH * (a2 - 1.0) + 1.0;
    float  D = a2 / max(3.14159265 * denom * denom, 1e-5);
    float  k = (roughness + 1.0);
    k = k * k / 8.0;
    float  Gv = NdotV / (NdotV * (1.0 - k) + k);
    float  Gl = NdotL / (NdotL * (1.0 - k) + k);
    float  G = Gv * Gl;
    float3 specular = (D * G * F) / max(4.0 * NdotV * NdotL, 1e-5);

    float3 diffuse = albedo * lit;
    float3 ambient_part = albedo * g_ambient.xyz;
    float3 direct = ambient_part + (diffuse - ambient_part) * atten
                  + specular * NdotL * atten * 2.0;
    return direct;
}

/* ============================ 顶点着色器 ============================ */

struct VSIn
{
    float3 pos    : POSITION;
    float3 nrm    : NORMAL;
    float2 uv     : TEXCOORD0;
    float4 col    : COLOR0;
    float4 m0     : INST0;
    float4 m1     : INST1;
    float4 m2     : INST2;
    float4 m3     : INST3;
};

struct VSOut
{
    float4 pos  : SV_POSITION;
    float3 wpos : TEXCOORD0;
    float3 nrm  : TEXCOORD1;
    float2 uv   : TEXCOORD2;
    float4 col  : COLOR0;
};

VSOut VSMain(VSIn i)
{
    /* 实例化：单次绘制路径不使用 INST* 属性（C++ 侧切换 input layout，
     * 不依赖 shader 开关，避免旧版「实例属性始终 enabled 导致二次变换」的坑） */
    float4x4 model = float4x4(1, 0, 0, 0,
                              0, 1, 0, 0,
                              0, 0, 1, 0,
                              0, 0, 0, 1);
    if (g_params2.z > 0.5)
    {
        model = float4x4(i.m0, i.m1, i.m2, i.m3);
    }

    VSOut o;
    float4 wp = mul(model, float4(i.pos, 1.0));
    o.pos  = mul(g_mvp, wp);
    o.wpos = wp.xyz;
    o.nrm  = mul((float3x3)g_normal_mat, mul((float3x3)model, i.nrm));
    o.uv   = i.uv;
    o.col  = i.col;
    return o;
}

/* ============================ 像素着色器 ============================ */

/* mode: 0 = 光照实体(PBS)  1 = 线框/平涂  2 = 无光照实体(emissive/透明)  3 = INDEXED 分块
 *       9 = 贴花法线合成（写入 nb，由全屏 pass 调用前先拷贝 na） */
float4 PSMain(VSOut i) : SV_TARGET
{
    int   mode      = (int)round(g_params2.x);
    int   debug     = (int)round(g_params2.y);
    float opacity   = g_params.y;
    float emissive_k= g_params.z;
    float emissive_on = g_params.w;
    float nstrength = g_params.x;

    /* ---------- mode 9：贴花法线合成（独立 mesh，自身 UV）---------- */
    if (mode == 9)
    {
        uint tw = 0, th = 0;
        g_scene_normal_tex.GetDimensions(tw, th);
        float2 suv = i.pos.xy / float2(max((float)tw, 1.0), max((float)th, 1.0));
        float4 hn = g_scene_normal_tex.Sample(g_smp, suv);
        float3 hullN = normalize(hn.rgb * 2.0 - 1.0);
        float  keep_gloss = hn.a;
        float4 nmap = (g_mat.x > 0.5) ? g_tex.Sample(g_smp, glUV(i.uv))
                                     : float4(0.5, 0.5, 1.0, 1.0);
        float3 n_ts9 = float3(nmap.x * 2.0 - 1.0, nmap.y * 2.0 - 1.0, 0.0);
        n_ts9.z = sqrt(max(1.0 - (n_ts9.x * n_ts9.x + n_ts9.y * n_ts9.y), 0.0));
        float3 decal_n = normalize(n_ts9);
        float3 merged = normalize(hullN + (decal_n - float3(0.0, 0.0, 1.0)));
        return float4(merged * 0.5 + 0.5, keep_gloss);
    }

    /* ---------- mode 3：INDEXED 分块材质（公式与 GLSL 完全一致） ---------- */
    if (mode == 3)
    {
        int2 imsz = int2(0, 0);
        uint tw = 0, th = 0;
        g_matid_tex.GetDimensions(tw, th);
        imsz = int2((int)tw, (int)th);

        float2 noise_uv = i.uv * 48.0;
        float2 noise_raw = g_noise_tex.Sample(g_smp, glUV(noise_uv, 0.0)).xy;
        float  floating = dot(normalize(i.nrm), float3(0.0, 1.0, 0.0));
        float2 noise_sel = (floating > 0.96) ? float2(noise_raw.x, noise_raw.x) : noise_raw;
        float2 noise2 = noise_sel * 2.0 - 1.0;
        float2 muv_uv = i.uv + noise2 * (1.0 / (48.0 * 52.0));
        float2 muv = floor(muv_uv * float2(imsz) + 0.5) / float2(imsz);

        /* 官方 gather4 + 一致性选择：取 4 邻材质 ID，选「与其余最一致」者 */
        float4 m4 = g_matid_tex.Gather(g_smp_point, glUV(muv));
        float4 mid4 = min(floor(m4 * 255.0 + 0.5), 195.0);
        float d0 = abs(mid4.x - mid4.y) + abs(mid4.x - mid4.z) + abs(mid4.x - mid4.w);
        float d1 = abs(mid4.y - mid4.x) + abs(mid4.y - mid4.z) + abs(mid4.y - mid4.w);
        float d2 = abs(mid4.z - mid4.x) + abs(mid4.z - mid4.y) + abs(mid4.z - mid4.w);
        float d3 = abs(mid4.w - mid4.x) + abs(mid4.w - mid4.y) + abs(mid4.w - mid4.z);
        float dm = min(min(d0, d1), min(d2, d3));
        float sel = (dm == d0) ? mid4.x : (dm == d1) ? mid4.y : (dm == d2) ? mid4.z : mid4.w;
        int matId = (int)sel;

        float2 uv = i.uv * g_offset_scale[matId].zw + g_offset_scale[matId].xy;
        float  uang = g_rotation[matId].x;
        float  usa = sin(uang);
        float  uca = cos(uang);
        uv = float2(uv.x * uca + uv.y * usa, -uv.x * usa + uv.y * uca);

        float slice = max(g_tile_idx[matId].x, 0.0);
        float2 dudx = ddx(uv);
        float2 dudy = ddy(uv);
        float3 albedo = g_tiles_tex.SampleGrad(g_smp, glUV(uv, slice), dudx, dudy).rgb;

        float  g = g_mat.w;   /* gamma（默认 2.2） */
        float3 albedo_lin = pow(albedo, g);
        float3 tint_lin   = pow(g_tint[matId].rgb, g);
        float3 ref = g_remove[matId].rgb;
        float  sum = abs(albedo.x - ref.x) + abs(albedo.y - ref.y) + abs(albedo.z - ref.z);
        float  k = clamp((sum + 0.001) / max(g_tint[matId].w, 1e-4), 0.0, 1.0);
        float3 c = lerp(tint_lin, albedo_lin, k);

        float mslice = max(g_tile_idx[matId].z, 0.0);
        float3 mg = g_mg_tex.SampleGrad(g_smp, glUV(uv, mslice), dudx, dudy).rgb;
        float  f0_weight = mg.r;
        float  gloss = mg.g;

        float4 art4 = g_art_tex.Sample(g_smp, glUV(i.uv));
        float  am = clamp(art4.a * g_rotation[matId].y, 0.0, 1.0);
        c = lerp(c, art4.rgb, am);

        if (debug == 5)
        {
            return float4(am, am, am, 1.0);
        }

        float nslice = max(g_tile_idx[matId].y, 0.0);
        float3 ntex = g_normal_tex.SampleGrad(g_smp, glUV(uv, nslice), dudx, dudy).rgb;
        float3 n_ts = float3(ntex.x * 2.0 - 1.0, ntex.y * 2.0 - 1.0, 0.0);
        float  nz = n_ts.x * n_ts.x + n_ts.y * n_ts.y;
        n_ts.z = sqrt(max(1.0 - nz, 0.0));

        float3 a4 = g_alpha_n_map.Sample(g_smp, glUV(i.uv)).rgb;
        float3 n_a = float3(a4.x * 2.0 - 1.0, a4.y * 2.0 - 1.0, 0.0);
        float  nza = n_a.x * n_a.x + n_a.y * n_a.y;
        n_a.z = sqrt(max(1.0 - nza, 0.0));

        n_ts = normalize(n_ts + n_a - float3(0.0, 0.0, 1.0));
        n_ts.xy *= nstrength;
        float3 n_world = normalize(n_ts);

        if (g_params2.w > 0.5)   /* matid 伪彩诊断 */
        {
            float v = (float)matId / 195.0;
            return float4(v, v, v, 1.0);
        }

        /* debug 7：反照率 `_a` 直显。
         * INDEXED 的 `_a` 是 albedoArray（**非 sRGB** 上传）⇒ 直接输出采样原值，
         * 与 Python 侧解码同一张 DDS 的字节**逐像素可比**，用来验证通道上传是否正确。 */
        if (debug == 7)
        {
            return float4(albedo, 1.0);
        }

        float3 litL = normalize(g_light_pos.xyz - i.wpos);
        float  diff2 = max(dot(n_world, litL), 0.0);
        float  hl2 = diff2 * 0.5 + 0.5;
        float3 lit2 = g_ambient.xyz + (1.0 - g_ambient.xyz) * hl2;
        float3 col = pbr_light(c, n_world, f0_weight, gloss, lit2, i.wpos);
        col = pow(col, 1.0 / 2.2);
        return float4(col, 1.0);
    }

    /* ---------- 通用路径 ---------- */
    float4 base = i.col;
    bool is_tex = (g_mat.x > 0.5);
    if (is_tex)
    {
        base = g_tex.Sample(g_smp, glUV(i.uv));
    }

    /* debug 7：反照率 `_a` 直显。PBS 的 diffuseMap 走 **sRGB** 上传（硬件已线性化），
     * 这里反编码回存储值，与 Python 解码的 DDS 字节逐像素可比。 */
    if (debug == 7)
    {
        return float4(pow(max(base.rgb, 0.0), 1.0 / 2.2), 1.0);
    }

    if (mode == 1)
    {
        /* 线框/平涂：直接显色 */
        return float4(base.rgb, 1.0);
    }

    float3 N = normalize(i.nrm);

    /* 标准 PBS 法线贴图：材质声明了 normalMap 则只遵循法线贴图 */
    if (g_mat.y > 0.5)
    {
        float3 nm = g_normal_map.Sample(g_smp, glUV(i.uv)).rgb;
        float3 n_ts = float3(nm.x * 2.0 - 1.0, nm.y * 2.0 - 1.0, 0.0);
        n_ts.xy *= nstrength;
        n_ts.z = sqrt(max(1.0 - (n_ts.x * n_ts.x + n_ts.y * n_ts.y), 0.0));
        N = normalize(n_ts);
    }

    /* _mg（metallicGlossMap）：R=F0 混合权重，G=gloss，B=发光/涂装强度 */
    float f0_weight = 0.0;
    float gloss = 0.0;
    float emit = 0.0;
    if (g_mat.z > 0.5)
    {
        float3 mg = g_mg_map.Sample(g_smp, glUV(i.uv)).rgb;
        f0_weight = mg.r;
        gloss = mg.g;
        emit = mg.b;
    }

    float3 n = N;
    float3 litL = normalize(g_light_pos.xyz - i.wpos);
    float  diff = max(dot(n, litL), 0.0);
    float  hl = diff * 0.5 + 0.5;          /* half-Lambert：远侧永不黑 */
    float3 lit = g_ambient.xyz + (1.0 - g_ambient.xyz) * hl;

    float3 rgb2;
    if (mode == 2)
    {
        rgb2 = base.rgb;
        if (emissive_on > 0.5)
        {
            float em = (g_mat.z > 0.5) ? emit : base.b;
            rgb2 = base.rgb + base.rgb * em * emissive_k;
        }
    }
    else
    {
        rgb2 = pbr_light(base.rgb, n, f0_weight, gloss, lit, i.wpos);
        if (emissive_on > 0.5)
        {
            float em = (g_mat.z > 0.5) ? emit : base.b;
            rgb2 += base.rgb * em * emissive_k;
        }
    }

    if (debug == 5)
    {
        rgb2 = float3(emit, emit, emit);
    }

    if (is_tex)
    {
        rgb2 = pow(rgb2, 1.0 / 2.2);
    }
    return float4(rgb2, base.a * opacity);
}

/* ============================ Pass1：MRT 变体 ============================ */
/* 与 PSMain 使用同一套公式，只改输出：未打光 albedo / 世界法线 / 世界坐标。
 * .a 通道携带 F0 混合权重与 gloss，供最终光照 pass 重建（架构文档 §7 Pass1）。 */

struct PSOutMRT
{
    float4 color  : SV_TARGET0;   // rgb = albedo(linear), a = f0_weight
    float4 normal : SV_TARGET1;   // rgb = world normal [0,1], a = gloss
    float4 world  : SV_TARGET2;   // xyz = world position
};

PSOutMRT PSMainMRT(VSOut i)
{
    int   mode    = (int)round(g_params2.x);
    float nstrength = g_params.x;
    float3 N = normalize(i.nrm);
    float3 albedo = i.col.rgb;
    float  f0_weight = 0.0;
    float  gloss = 0.0;

    if (mode == 3)
    {
        /* INDEXED 分块（公式与 PSMain 完全一致） */
        uint tw = 0, th = 0;
        g_matid_tex.GetDimensions(tw, th);
        int2 imsz = int2((int)tw, (int)th);

        float2 noise_uv = i.uv * 48.0;
        float2 noise_raw = g_noise_tex.Sample(g_smp, glUV(noise_uv, 0.0)).xy;
        float  floating = dot(normalize(i.nrm), float3(0.0, 1.0, 0.0));
        float2 noise_sel = (floating > 0.96) ? float2(noise_raw.x, noise_raw.x) : noise_raw;
        float2 noise2 = noise_sel * 2.0 - 1.0;
        float2 muv_uv = i.uv + noise2 * (1.0 / (48.0 * 52.0));
        float2 muv = floor(muv_uv * float2(imsz) + 0.5) / float2(imsz);

        float4 m4 = g_matid_tex.Gather(g_smp_point, glUV(muv));
        float4 mid4 = min(floor(m4 * 255.0 + 0.5), 195.0);
        float d0 = abs(mid4.x - mid4.y) + abs(mid4.x - mid4.z) + abs(mid4.x - mid4.w);
        float d1 = abs(mid4.y - mid4.x) + abs(mid4.y - mid4.z) + abs(mid4.y - mid4.w);
        float d2 = abs(mid4.z - mid4.x) + abs(mid4.z - mid4.y) + abs(mid4.z - mid4.w);
        float d3 = abs(mid4.w - mid4.x) + abs(mid4.w - mid4.y) + abs(mid4.w - mid4.z);
        float dm = min(min(d0, d1), min(d2, d3));
        float sel = (dm == d0) ? mid4.x : (dm == d1) ? mid4.y : (dm == d2) ? mid4.z : mid4.w;
        int matId = (int)sel;

        float2 uv = i.uv * g_offset_scale[matId].zw + g_offset_scale[matId].xy;
        float uang = g_rotation[matId].x;
        float usa = sin(uang);
        float uca = cos(uang);
        uv = float2(uv.x * uca + uv.y * usa, -uv.x * usa + uv.y * uca);

        float slice = max(g_tile_idx[matId].x, 0.0);
        float2 dudx = ddx(uv);
        float2 dudy = ddy(uv);
        float3 tile_albedo = g_tiles_tex.SampleGrad(g_smp, glUV(uv, slice), dudx, dudy).rgb;

        float  g = g_mat.w;
        float3 albedo_lin = pow(tile_albedo, g);
        float3 tint_lin = pow(g_tint[matId].rgb, g);
        float3 ref = g_remove[matId].rgb;
        float  sum = abs(tile_albedo.x - ref.x) + abs(tile_albedo.y - ref.y)
                   + abs(tile_albedo.z - ref.z);
        float  k = clamp((sum + 0.001) / max(g_tint[matId].w, 1e-4), 0.0, 1.0);
        float3 c = lerp(tint_lin, albedo_lin, k);

        float mslice = max(g_tile_idx[matId].z, 0.0);
        float3 mg = g_mg_tex.SampleGrad(g_smp, glUV(uv, mslice), dudx, dudy).rgb;
        f0_weight = mg.r;
        gloss = mg.g;

        float4 art4 = g_art_tex.Sample(g_smp, glUV(i.uv));
        float  am = clamp(art4.a * g_rotation[matId].y, 0.0, 1.0);
        c = lerp(c, art4.rgb, am);
        albedo = c;

        float nslice = max(g_tile_idx[matId].y, 0.0);
        float3 ntex = g_normal_tex.SampleGrad(g_smp, glUV(uv, nslice), dudx, dudy).rgb;
        float3 n_ts = float3(ntex.x * 2.0 - 1.0, ntex.y * 2.0 - 1.0, 0.0);
        n_ts.z = sqrt(max(1.0 - (n_ts.x * n_ts.x + n_ts.y * n_ts.y), 0.0));
        float3 a4 = g_alpha_n_map.Sample(g_smp, glUV(i.uv)).rgb;
        float3 n_a = float3(a4.x * 2.0 - 1.0, a4.y * 2.0 - 1.0, 0.0);
        n_a.z = sqrt(max(1.0 - (n_a.x * n_a.x + n_a.y * n_a.y), 0.0));
        n_ts = normalize(n_ts + n_a - float3(0.0, 0.0, 1.0));
        n_ts.xy *= nstrength;
        N = normalize(n_ts);
    }
    else
    {
        if (g_mat.x > 0.5)
        {
            albedo = g_tex.Sample(g_smp, glUV(i.uv)).rgb;
        }
        if (g_mat.y > 0.5)
        {
            float3 nm = g_normal_map.Sample(g_smp, glUV(i.uv)).rgb;
            float3 n_ts = float3(nm.x * 2.0 - 1.0, nm.y * 2.0 - 1.0, 0.0);
            n_ts.xy *= nstrength;
            n_ts.z = sqrt(max(1.0 - (n_ts.x * n_ts.x + n_ts.y * n_ts.y), 0.0));
            N = normalize(n_ts);
        }
        if (g_mat.z > 0.5)
        {
            float3 mg = g_mg_map.Sample(g_smp, glUV(i.uv)).rgb;
            f0_weight = mg.r;
            gloss = mg.g;
        }
    }

    PSOutMRT o;
    o.color  = float4(albedo, f0_weight);
    o.normal = float4(N * 0.5 + 0.5, gloss);
    o.world  = float4(i.wpos, 1.0);
    return o;
}

/* ============================ 全屏 pass ============================ */
/* mode 10 = 拷贝法线；11 = 最终光照；12/13/14 = debug 通道直显。
 * 等价于旧版 gl_VertexID 全屏三角形（TEX_VERT_SRC）+ u_mode 10/11/12/13/14。 */

struct FSOut
{
    float4 pos : SV_POSITION;
};

FSOut VSFullscreen(uint vid : SV_VertexID)
{
    FSOut o;
    float2 p = float2(float((vid << 1) & 2), float(vid & 2));
    o.pos = float4(p * 2.0 - 1.0, 0.0, 1.0);
    return o;
}

float4 PSFullscreen(FSOut i) : SV_TARGET
{
    int mode = (int)round(g_params2.x);
    uint tw = 0, th = 0;
    g_scene_tex.GetDimensions(tw, th);
    float2 suv = i.pos.xy / float2(max((float)tw, 1.0), max((float)th, 1.0));

    if (mode == 10)
    {
        /* 拷贝源法线 → 中间缓冲（na / nb 打底，避免残留虚影） */
        return g_scene_normal_tex.Sample(g_smp, suv);
    }
    if (mode == 12)
    {
        return g_scene_final_tex.Sample(g_smp, suv);
    }
    if (mode == 13)
    {
        float m = g_scene_tex.Sample(g_smp, suv).a;
        return float4(m, m, m, 1.0);
    }
    if (mode == 14)
    {
        float gl = g_scene_final_tex.Sample(g_smp, suv).a;
        return float4(gl, gl, gl, 1.0);
    }
    if (mode == 15)
    {
        /* debug 7（延迟管线）：反照率 `_a` 直显。MRT 存的是**线性**反照率，
         * 反编码回存储值以便与源 DDS 字节对比。 */
        float3 a = g_scene_tex.Sample(g_smp, suv).rgb;
        return float4(pow(max(a, 0.0), 1.0 / 2.2), 1.0);
    }

    /* mode 11：最终光照（读 Hull Albedo + Final Normal + 世界坐标） */
    float4 sc = g_scene_tex.Sample(g_smp, suv);
    float3 albedo = sc.rgb;
    float  f0_weight = sc.a;
    float4 sn = g_scene_final_tex.Sample(g_smp, suv);
    float3 N = normalize(sn.rgb * 2.0 - 1.0);
    float  gloss = sn.a;
    float3 worldPos = g_scene_world_tex.Sample(g_smp, suv).xyz;

    float3 litL = normalize(g_light_pos.xyz - worldPos);
    float  diff = max(dot(N, litL), 0.0);
    float  hl = diff * 0.5 + 0.5;
    float3 lit = g_ambient.xyz + (1.0 - g_ambient.xyz) * hl;
    float3 col = pbr_light(albedo, N, f0_weight, gloss, lit, worldPos);
    col = pow(col, 1.0 / 2.2);
    return float4(col, 1.0);
}
