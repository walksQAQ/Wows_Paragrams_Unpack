"""
geometry_renderer.py —— 舰船 3D 渲染引擎（QOpenGLWidget + PyOpenGL）。

直接在 QOpenGLWidget 的 GL 上下文内调用 OpenGL（无需 ModernGL 独立上下文层）。

- 船体：可选漫反射贴图（DXT1/BC 压缩纹理直接上传 GPU 采样）+ 光照
- 装甲：半透明厚度着色（无贴图）
- 单个 GLSL 程序（模式 0=光照实体 1=线框 2=无光照实体）
- 轨道相机交互 + 自动取景（按 2D 投影精确框选舰船）
"""

from __future__ import annotations

import ctypes
import time

import numpy as np
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QSurfaceFormat, QMouseEvent, QWheelEvent, QPainter, QColor
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from OpenGL import GL

# 关闭 PyOpenGL 每次调用自动抛 GL 错误异常：避免 paintGL 中途因单个 GL 错误
# 中断导致整帧渲染缺失。错误改为静默/手动检查。
GL.ERROR_CHECKING = False

from models.camera import OrbitCamera
from models.geometry_transform import prepare_render_mesh

# ── 装甲展示重构常量（参考 landaire/wows-toolkit）─────────────────────────
PLATE_EDGE_COLOR = (0.0, 0.0, 0.0, 0.9)       # 板块边界描边色
HIGHLIGHT_HOVER = (0.0, 0.9, 1.0, 0.5)        # 悬停高亮（青）
HIGHLIGHT_SELECT = (1.0, 0.6, 0.1, 0.6)       # 选中高亮（橙）

# ── OpenGL 3.3 Core 表面格式（在首个 QOpenGLWidget 创建前生效）──────────────
_gl_format_done = False


def _ensure_gl_format():
    global _gl_format_done
    if _gl_format_done:
        return
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    QSurfaceFormat.setDefaultFormat(fmt)
    _gl_format_done = True


_ensure_gl_format()

VERT_SRC = """
#version 330 core
in vec3 in_position;
in vec3 in_normal;
in vec2 in_uv;
in vec4 in_color;
uniform mat4 u_mvp;
uniform mat3 u_normal_mat;
out vec4 v_color;
out vec3 v_normal;
out vec2 v_uv;
void main() {
    gl_Position = u_mvp * vec4(in_position, 1.0);
    v_normal = u_normal_mat * in_normal;
    v_color = in_color;
    v_uv = in_uv;
}
"""

TEX_VERT_SRC = """
#version 400 core
out vec4 v_color;
out vec3 v_normal;
out vec2 v_uv;
void main() {
    vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
    v_color = vec4(1.0);
    v_normal = vec3(0.0, 0.0, 1.0);
    v_uv = vec2(0.0);
}
"""

FRAG_SRC = """
#version 400 core
in vec4 v_color;
in vec3 v_normal;
in vec2 v_uv;
uniform int u_mode;        // 0=光照实体 1=线框 2=无光照实体 3=INDEXED分块
uniform float u_opacity;
uniform vec3 u_light_dir;
uniform vec3 u_ambient;
uniform sampler2D u_tex;
uniform int u_has_tex;
// emissive 自发光（ship_emissive_material.fx 等）：无光照 + diffuse blue 通道做自发光强度
// （用户要求：先忽略 _n/_mg 贴图，只用 diffuse 基础渲染）
uniform float u_emissive;     // 1=emissive 渲染（u_mode==2 时生效）
uniform float u_emissive_k;   // 自发光强度系数（emissivePower）
// INDEXED 分块涂装（ship_material_indexed.fx，ps_5_0 官方公式，2026-08-24 运行时抓取）
uniform sampler2D u_matid_tex;   // materialIdMap（R=材质ID 0~195）
uniform sampler2DArray u_tiles_tex; // albedoArray（2DArray，每层=船 tile 色块）
uniform sampler2DArray u_normal_tex; // normalArray（2DArray，每层=法线 tile）
uniform sampler2D u_alpha_n_map; // normalMap（全船 _alpha_n.dds，@v_uv，与 normalArray 合成法线）
uniform sampler2D u_art_tex;     // artMap（艺术涂装叠加层）
uniform sampler2DArray u_noise_tex; // rgbNoiseMap（materialIdMap 采样扰动）
// 标准 PBS 法线贴图（仅当材质声明 normalMap/g_normalMap；未声明则用几何法线）
uniform sampler2D u_normal_map;
uniform int u_has_normal_map;
uniform vec4 u_offset_scale[196]; // offsetScaleMatIdArr：每材质ID (offset.xy, scale.zw)
uniform vec4 u_rotation[196];    // rotationMatIdArr(.x=角度) + artStrengthMatIdArr(.y=BaseStrength)
uniform vec4 u_tile_idx[196];    // tileIdxMatIdArr：每材质ID (albedo层, normal层, MG层, disableMGNCamo)
uniform vec4 u_tint[196];        // albedoTintMatIdArr：每材质ID 调色(RGB) + 强度(w)
uniform vec4 u_remove[196];      // albedoToRemoveTintMatIdArr：每材质ID 要替换为tint的色
uniform float u_gamma;           // tint 混合 gamma 系数（cb1[19].x）
// u_mode==4：轻量 deferred compositing —— decal_tech 独立法线细节层（读船体 surface MRT）
uniform sampler2D u_scene_tex;         // MRT 附件0：船体未打光 albedo（linear）
uniform sampler2D u_scene_normal_tex;  // MRT 附件1：船体世界法线
uniform vec2 u_viewport;               // 视口尺寸（换算屏幕 UV）
uniform int u_mrt;                     // 1=输出未打光 albedo+世界法线到 MRT（轻量 deferred surface）
uniform int u_debug_mode;              // Normal 数据链调试：1=RAW normalArray 2=RAW normalMap(g_normalMap) 3=Hull最终N 4=Decal RAW 5=Decal合成N 8=同时显示
uniform int u_use_scene_normal;        // 1=船体打光用 Final Normal(附件2)（含 decal 法线）
uniform sampler2D u_scene_final_tex;   // MRT 附件2：Final Normal（Hull+decal 合成，供打光）
out vec4 fragColor;
out vec4 fragNormal;                   // MRT 附件1 输出（世界法线，[0,1] 编码）
void main() {
    vec4 base = v_color;
    bool is_tex = (u_has_tex == 1);
    if (is_tex) {
        base = texture(u_tex, v_uv);
    }
    if (u_mode == 3) {
        // INDEXED（2.0 技术，官方 ship_material_indexed.fx ps_5_0 对齐，2026-08-24）：
        //  materialIdMap → matId；uv'=rotate(u*scale+offset)；alb=albedoArray[slice](uv',d)
        //  tint：lerp(tint_lin, alb_lin, sat((sum|alb-ref|)/tint.w))；法线 normalArray .xy 重建 z
        ivec2 imsz = textureSize(u_matid_tex, 0);
        // ★ rgbNoise 按官方逻辑（indexed_sm5_hit22.dxbc.asm）：
        //   noise_uv = v_uv * blendNoiseParams.x(=48)；振幅 = 1/(48*52)=1/2496；
        //   面朝上（dot(世界法线, (0,1,0)) > 0.96）只用噪声红通道(1D)，否则 xy(2D)；
        //   muv = v_uv + noise_decode * 振幅。这是**全局**扰动 materialIdMap 采样坐标（非按 matId）。
        vec2 noise_uv = v_uv * 48.0;
        vec2 noise_raw = texture(u_noise_tex, vec3(noise_uv, 0.0)).xy;
        float floating = dot(normalize(v_normal), vec3(0.0, 1.0, 0.0));
        vec2 noise_sel = (floating > 0.96) ? vec2(noise_raw.x) : noise_raw;
        vec2 noise2 = noise_sel * 2.0 - 1.0;
        vec2 muv_uv = v_uv + noise2 * (1.0 / (48.0 * 52.0));
        // materialIdMap → matId：官方**单 texel 中心采样**（2026-08-24 抽取证实 matIdMap 是
        // 干净分块 99.7% 相邻同 matId，不用 textureGather 中值平滑，否则会模糊材质边界）
        vec2 muv = (floor(muv_uv * vec2(imsz) + 0.5)) / vec2(imsz);
        float mval = texture(u_matid_tex, muv).r;
        int matId = int(min(floor(mval * 255.0 + 0.5), 195.0));
        // uv/scale + offset + rotate（主 matId 变换，供法线/tint）
        // ★ 官方公式（indexed_sm5_hit22.dxbc.asm 反汇编确认）：
        //   mad r4.yz, v1.xxyx, cb0[r0.z+19].zzwz, cb0[r0.z+19].xxyx
        //   = uv = v_uv * offsetScaleMatIdArr[matId].zw + offsetScaleMatIdArr[matId].xy  ← 乘法
        // ★ Reciprocal 优化：assets 里 .zw 是 CPU 端**原始尺寸**（38/25/…），CPU 提交时预取倒数，
        //   故 `u_offset_scale` 上传的是 `1/raw`；shader 保持乘法 `v_uv * sc`，sc 已是倒数。
        //   scale<=0 的退化材质（matId 175）回退 1/38（与倒数空间一致）。
        vec4 os = u_offset_scale[matId];
        vec2 sc = (os.zw.x > 0.0 && os.zw.y > 0.0) ? os.zw : vec2(1.0 / 38.0, 1.0 / 38.0);
        vec2 uv = v_uv * sc + os.xy;
        float ang = u_rotation[matId].x;
        float sa = sin(ang); float ca = cos(ang);
        uv = vec2(uv.x*ca + uv.y*sa, -uv.x*sa + uv.y*ca);
        float slice = max(u_tile_idx[matId].x, 0.0);
        vec2 dudx = dFdx(uv);
        vec2 dudy = dFdy(uv);
        // albedo：单材质单 tile（官方行为，不平均 4 个候选材质，避免边界模糊）
        vec3 albedo = textureGrad(u_tiles_tex, vec3(uv, slice), dudx, dudy).rgb;
        // tint 混合（官方：lerp(tint_lin, alb_lin, sat(sum|albedo-ref| / tint.w))）
        float g = u_gamma;
        vec3 albedo_lin = pow(albedo, vec3(g));
        vec3 tint_lin = pow(u_tint[matId].rgb, vec3(g));
        vec3 ref = u_remove[matId].rgb;
        float sum = abs(albedo.x-ref.x) + abs(albedo.y-ref.y) + abs(albedo.z-ref.z);
        float k = clamp((sum + 0.001) / max(u_tint[matId].w, 1e-4), 0.0, 1.0);
        vec3 c = mix(tint_lin, albedo_lin, k);
        // artMap 艺术涂装(camo)覆盖（2026-08-24 结合 x64dbg+fxo 确认）：
        //   - 全船 512×512 覆盖层，用船体全图 UV(v_uv) 采样，**不用分块 tile uv**（否则盖黑）
        //   - camo 强度 = art.a * artStrengthMatIdArr[matId].x(=u_art_strength)
        //   - artMap 以 sRGB 内格式上传，GPU 硬件解码为 linear，故在 linear 空间 mix
        vec4 art4 = texture(u_art_tex, v_uv);
        // BaseStrength = artStrengthMatIdArr[matId].x，已并入 u_rotation[matId].y
        float am = clamp(art4.a * u_rotation[matId].y, 0.0, 1.0);
        c = mix(c, art4.rgb, am);
        // 法线：normalArray(每材质 tile) + normalMap(_alpha_n, 全船) 合成（对齐官方 asm）：
        //   t20(normalArray) 解码 + t14(normalMap@v1.xy) 解码 → add → add(0,0,-1) → normalize
        float nslice = max(u_tile_idx[matId].y, 0.0);
        vec3 ntex = textureGrad(u_normal_tex, vec3(uv, nslice), dudx, dudy).rgb;
        vec3 n_ts = vec3(ntex.x * 2.0 - 1.0, ntex.y * 2.0 - 1.0, 0.0);
        float nz = n_ts.x*n_ts.x + n_ts.y*n_ts.y;
        n_ts.z = sqrt(max(1.0 - nz, 0.0));
        // 全船 normalMap（alpha_n）：@v_uv 采样，解码，再与 normalArray 重组（减 (0,0,1)）
        vec3 a4 = texture(u_alpha_n_map, v_uv).rgb;
        vec3 n_a = vec3(a4.x * 2.0 - 1.0, a4.y * 2.0 - 1.0, 0.0);
        float nza = n_a.x*n_a.x + n_a.y*n_a.y;
        n_a.z = sqrt(max(1.0 - nza, 0.0));
        n_ts = normalize(n_ts + n_a - vec3(0.0, 0.0, 1.0));
        vec3 N = normalize(v_normal);
        vec3 up = abs(N.y) < 0.999 ? vec3(0.0,1.0,0.0) : vec3(1.0,0.0,0.0);
        vec3 T = normalize(cross(up, N));
        vec3 B = normalize(cross(N, T));
        vec3 n_world = normalize(T*n_ts.x + B*n_ts.y + N*n_ts.z);
        if (u_mrt == 0 && (u_debug_mode >= 1 && u_debug_mode <= 3 || u_debug_mode == 8)) {
            // Normal 数据链分段调试（PASS1a/1b/2；8=与 decal 法线同时显示）
            if (u_debug_mode == 1) {
                // PASS1a：RAW normalArray（texture array 采样原始值，未合成/TBN/normalize）
                fragColor = vec4(ntex.rgb, 1.0);
            } else if (u_debug_mode == 2) {
                // PASS1b：RAW normalMap / g_normalMap（alpha_n 采样原始值）
                fragColor = vec4(a4.rgb, 1.0);
            } else {
                // PASS2(3) / debug8：normalArray+normalMap 合成 → TBN → 最终 hull world normal
                fragColor = vec4(normalize(n_world) * 0.5 + 0.5, 1.0);
            }
            return;
        }
        if (u_mrt == 1) {
            // 轻量 deferred surface：存未打光 albedo(linear，已含 tint/art) + 世界法线
            fragColor = vec4(c, 1.0);
            fragNormal = vec4(n_world * 0.5 + 0.5, 1.0);
        } else {
            if (u_use_scene_normal == 1) {
                vec2 suv2 = gl_FragCoord.xy / u_viewport;
                n_world = normalize(texture(u_scene_final_tex, suv2).rgb * 2.0 - 1.0);
            }
            // 光照（临时简化 half-Lambert，PBR 后续）
            float diff2 = max(dot(n_world, -u_light_dir), 0.0);
            float hl2 = diff2 * 0.5 + 0.5;
            vec3 lit2 = u_ambient + (1.0 - u_ambient) * hl2;
            c *= lit2;
            c = pow(c, vec3(1.0 / 2.2));
            fragColor = vec4(c, 1.0);
        }
        return;
    }
    if (u_mode == 4) {
        // 轻量 deferred compositing：decal_tech 独立法线细节层（Normal Detail Layer）。
        // 读船体 surface MRT（u_scene_tex=未打光 albedo，u_scene_normal_tex=原世界法线），
        // 用自身 g_normalMap 构造 decal 世界法线，与原法线合成，再打一次光。
        // ★ g_mode=4 保留（本层是「法线增强/叠加」，非独立完整 PBR 材质）。
        vec2 suv = gl_FragCoord.xy / u_viewport;
        suv.y = 1.0 - suv.y;
        vec3 base_albedo = texture(u_scene_tex, suv).rgb;          // 船体未打光 albedo(linear)
        vec3 baseN = normalize(texture(u_scene_normal_tex, suv).rgb * 2.0 - 1.0);
        // 自身 g_normalMap → tangent 空间 → 世界（相对自身几何法线 v_normal）
        vec4 nmap = (u_has_tex == 1) ? texture(u_tex, v_uv) : vec4(0.5, 0.5, 1.0, 0.0);
        vec3 n_ts = vec3(nmap.x * 2.0 - 1.0, nmap.y * 2.0 - 1.0, 0.0);
        n_ts.z = sqrt(max(1.0 - (n_ts.x * n_ts.x + n_ts.y * n_ts.y), 0.0));
        n_ts = normalize(n_ts);
        vec3 N = normalize(v_normal);
        vec3 up = abs(N.y) < 0.999 ? vec3(0.0, 1.0, 0.0) : vec3(1.0, 0.0, 0.0);
        vec3 T = normalize(cross(up, N));
        vec3 B = normalize(cross(N, T));
        vec3 decal_n = normalize(T * n_ts.x + B * n_ts.y + N * n_ts.z);
        // 合成：把 decal 的法线扰动增量(相对 decal 自身几何法线 N)叠加到船体 baseN。
        // ★ 修正：此前误减世界空间 (0,0,1)（照抄 INDEXED 切线空间合成），会把世界法线
        //   整体下压 → 凹陷。改为「船体法线 + decal 扰动增量」，方向为凸起。
        //   g_mode=4 精确合并方式待逆向确认，此处保证方向正确。
        vec3 merged = normalize(baseN + (decal_n - N));
        float diff = max(dot(merged, -u_light_dir), 0.0);
        float hl = diff * 0.5 + 0.5;
        vec3 lit = u_ambient + (1.0 - u_ambient) * hl;
        vec3 col = base_albedo * lit;
        col = pow(col, vec3(1.0 / 2.2));
        // decal 是法线细节层：覆盖船体表面（颜色=船体 albedo，法线=合成后）。
        // 遮挡由 decal 几何/UV 决定，**不用 g_normalMap 的 alpha**（normal map 的 alpha
        // 不是 opacity，几乎为 0 会导致 decal 全透明 → 合并后完全不可见）。
        float mask = 1.0 * u_opacity;
        fragColor = vec4(col, mask);
        return;
    }
    if (u_mode == 5) {
        // PASS3：decal_tech 独立 Mesh 的法线 debug（用自己的 UV(v_uv) 采样 g_normalMap）。
        // decal 不是完整材质，必须有独立 mesh/draw call + 自己的 UV；此处只显示法线信息。
        vec4 nmap5 = (u_has_tex == 1) ? texture(u_tex, v_uv) : vec4(0.5, 0.5, 1.0, 0.0);
        if (u_debug_mode == 4) {
            // PASS3a：RAW g_normalMap 原始值（未合成/TBN/normalize）
            fragColor = vec4(nmap5.rgb, 1.0);
        } else {
            // PASS3b：g_mode=4 处理后法线（tangent→world）
            vec3 n5 = vec3(nmap5.x * 2.0 - 1.0, nmap5.y * 2.0 - 1.0, 0.0);
            n5.z = sqrt(max(1.0 - (n5.x * n5.x + n5.y * n5.y), 0.0));
            n5 = normalize(n5);
            vec3 N5 = normalize(v_normal);
            vec3 up5 = abs(N5.y) < 0.999 ? vec3(0.0, 1.0, 0.0) : vec3(1.0, 0.0, 0.0);
            vec3 T5 = normalize(cross(up5, N5));
            vec3 B5 = normalize(cross(N5, T5));
            vec3 dn = normalize(T5 * n5.x + B5 * n5.y + N5 * n5.z);
            fragColor = vec4(normalize(dn) * 0.5 + 0.5, 1.0);
        }
        return;
    }
    if (u_mode == 9) {
        // Normal-only decal：读 normal_a(Hull Normal)，合成 decal 法线，写 normal_b(Final Normal)。
        vec2 suv = gl_FragCoord.xy / u_viewport;
        vec3 hullN = normalize(texture(u_scene_normal_tex, suv).rgb * 2.0 - 1.0);
        vec4 nmap = (u_has_tex == 1) ? texture(u_tex, v_uv) : vec4(0.5, 0.5, 1.0, 1.0);
        vec3 n_ts = vec3(nmap.x * 2.0 - 1.0, nmap.y * 2.0 - 1.0, 0.0);
        n_ts.z = sqrt(max(1.0 - (n_ts.x * n_ts.x + n_ts.y * n_ts.y), 0.0));
        n_ts = normalize(n_ts);
        vec3 N = normalize(v_normal);
        vec3 up = abs(N.y) < 0.999 ? vec3(0.0, 1.0, 0.0) : vec3(1.0, 0.0, 0.0);
        vec3 T = normalize(cross(up, N));
        vec3 B = normalize(cross(N, T));
        vec3 decal_n = normalize(T * n_ts.x + B * n_ts.y + N * n_ts.z);
        vec3 merged = normalize(hullN + (decal_n - N));
        fragColor = vec4(merged * 0.5 + 0.5, 1.0);
        return;
    }
    if (u_mode == 10) {
        // Copy：fullscreen quad 读 Hull Normal(scene_normal_tex)，写 normal_a。
        vec2 suv = gl_FragCoord.xy / u_viewport;
        fragColor = texture(u_scene_normal_tex, suv);
        return;
    }
    if (u_mode == 11) {
        // 最终 Lighting：fullscreen quad 读 Hull Albedo + Final Normal，打光 → 默认 FBO。
        vec2 suv = gl_FragCoord.xy / u_viewport;
        vec3 albedo = texture(u_scene_tex, suv).rgb;
        vec3 N = normalize(texture(u_scene_final_tex, suv).rgb * 2.0 - 1.0);
        float diff = max(dot(N, -u_light_dir), 0.0);
        float hl = diff * 0.5 + 0.5;
        vec3 lit = u_ambient + (1.0 - u_ambient) * hl;
        vec3 col = albedo * lit;
        col = pow(col, vec3(1.0 / 2.2));
        fragColor = vec4(col, 1.0);
        return;
    }
    if (u_mode == 12) {
        // Debug：直接显色「最终法线」（normal_b = Hull+Decal 合成），直观查看法线效果。
        vec2 suv = gl_FragCoord.xy / u_viewport;
        fragColor = texture(u_scene_final_tex, suv);
        return;
    }
    if (u_mode == 7) {
        // decal_tech 法线生效：读船体 surface MRT（未打光 albedo + 世界法线），
        // 用自身 g_normalMap 合成法线，打一次光，颜色 = 船体 albedo。
        vec2 suv = gl_FragCoord.xy / u_viewport;
        // MRT 纹理 v=0 即屏幕底部，与 gl_FragCoord.y 方向一致，无需翻转（翻转会读到背景）
        vec3 base_albedo = texture(u_scene_tex, suv).rgb;
        vec3 baseN = normalize(texture(u_scene_normal_tex, suv).rgb * 2.0 - 1.0);
        vec4 nmap = (u_has_tex == 1) ? texture(u_tex, v_uv) : vec4(0.5, 0.5, 1.0, 1.0);
        vec3 n_ts = vec3(nmap.x * 2.0 - 1.0, nmap.y * 2.0 - 1.0, 0.0);
        n_ts.z = sqrt(max(1.0 - (n_ts.x * n_ts.x + n_ts.y * n_ts.y), 0.0));
        n_ts = normalize(n_ts);
        vec3 N = normalize(v_normal);
        vec3 up = abs(N.y) < 0.999 ? vec3(0.0, 1.0, 0.0) : vec3(1.0, 0.0, 0.0);
        vec3 T = normalize(cross(up, N));
        vec3 B = normalize(cross(N, T));
        vec3 decal_n = normalize(T * n_ts.x + B * n_ts.y + N * n_ts.z);
        vec3 merged = normalize(decal_n);   // decal 法线直接作为该区域法线（凹凸由 g_normalMap 决定）
        float diff = max(dot(merged, -u_light_dir), 0.0);
        float hl = diff * 0.5 + 0.5;
        vec3 lit = u_ambient + (1.0 - u_ambient) * hl;
        vec3 col = base_albedo * lit;
        col = pow(col, vec3(1.0 / 2.2));
        fragColor = vec4(col, 1.0);
        return;
    }
    if (u_mode == 1) {
        fragColor = vec4(base.rgb, 1.0);
        return;
    }
    vec3 N = normalize(v_normal);
    // 标准 PBS 法线贴图：材质声明了 normalMap 则用其扰动几何法线（tangent 空间→世界空间）。
    // 仅对 u_mode==0（光照）生效；u_mode==2 无光照/自发光不需法线。
    if (u_has_normal_map == 1) {
        vec3 nm = texture(u_normal_map, v_uv).rgb;
        vec3 n_ts = vec3(nm.x * 2.0 - 1.0, nm.y * 2.0 - 1.0, 0.0);
        n_ts.z = sqrt(max(1.0 - (n_ts.x * n_ts.x + n_ts.y * n_ts.y), 0.0));
        n_ts = normalize(n_ts);
        vec3 up = abs(N.y) < 0.999 ? vec3(0.0, 1.0, 0.0) : vec3(1.0, 0.0, 0.0);
        vec3 T = normalize(cross(up, N));
        vec3 B = normalize(cross(N, T));
        N = normalize(T * n_ts.x + B * n_ts.y + N * n_ts.z);
    }
    if (u_mrt == 1) {
        // 轻量 deferred surface：标准 PBS/emissive 存未打光 albedo + 世界法线
        fragColor = vec4(base.rgb, base.a);
        fragNormal = vec4(N * 0.5 + 0.5, 1.0);
        return;
    }
    if (u_mrt == 0 && (u_debug_mode == 3 || u_debug_mode == 8)) {
        // PASS2/debug8：标准 PBS 法线贴图扰动后的最终 Normal 可视化
        fragColor = vec4(normalize(N) * 0.5 + 0.5, 1.0);
        return;
    }
    if (u_use_scene_normal == 1) {
        vec2 suv2 = gl_FragCoord.xy / u_viewport;
        N = normalize(texture(u_scene_final_tex, suv2).rgb * 2.0 - 1.0);
    }
    vec3 n = N;
    float diff = max(dot(n, -u_light_dir), 0.0);
    float hl = diff * 0.5 + 0.5;   // half-Lambert：远侧永不黑
    vec3 lit = u_ambient + (1.0 - u_ambient) * hl;
    vec3 rgb2;
    if (u_mode == 2) {
        rgb2 = base.rgb;
        if (u_emissive > 0.5) {
            // emissive：无光照 + diffuse blue 通道自发光增益（忽略 _n/_mg）
            float em = base.b;
            rgb2 = base.rgb * (1.0 + u_emissive_k * em);
        }
    } else {
        rgb2 = base.rgb * lit;
    }
    if (is_tex) {
        // 贴图已被硬件解码到线性空间，这里仅做线性→sRGB 编码输出
        rgb2 = pow(rgb2, vec3(1.0 / 2.2));
    }
    fragColor = vec4(rgb2, base.a * u_opacity);
}
"""

#: 单输出 fragColor 变体：用于**单 drawbuffer 目标**（decal normal pass / 默认 FBO）。
#: 移除 fragNormal 输出与赋值 —— 否则 `_program`（fragColor+fragNormal 两个输出）在只有
#: 1 个 drawbuffer 的目标上因「fragment 输出数 > drawbuffer 数」触发 GL_INVALID_OPERATION(1282)。
#: MRT(Pass1，scene_fbo 有 2 个 drawbuffer) 仍用完整 FRAG_SRC。
FRAG_SRC_SINGLE = FRAG_SRC.replace(
    "out vec4 fragColor;\n"
    "out vec4 fragNormal;                   // MRT 附件1 输出（世界法线，[0,1] 编码）",
    "out vec4 fragColor;",
).replace(
    "            fragNormal = vec4(n_world * 0.5 + 0.5, 1.0);",
    "",
).replace(
    "        fragNormal = vec4(N * 0.5 + 0.5, 1.0);",
    "",
)

#: 每顶点 12 个 float：position(3) + normal(3) + uv(2) + color(4)
_VERTEX_STRIDE = 48
_POS_OFFSET = 0
_NRM_OFFSET = 12
_UV_OFFSET = 24
_COL_OFFSET = 32

_UNIFORMS = ("u_mvp", "u_normal_mat", "u_mode", "u_opacity", "u_light_dir", "u_ambient",
             "u_tex", "u_has_tex", "u_emissive", "u_emissive_k",
             "u_matid_tex", "u_tiles_tex", "u_normal_tex", "u_alpha_n_map", "u_art_tex",
             "u_noise_tex", "u_offset_scale", "u_rotation", "u_tile_idx", "u_tint", "u_remove",
             "u_gamma", "u_scene_tex", "u_scene_normal_tex", "u_viewport", "u_mrt",
             "u_normal_map", "u_has_normal_map", "u_debug_mode", "u_scene_final_tex", "u_use_scene_normal")


def _compile_shader(shader_type: int, source: str) -> int:
    sh = GL.glCreateShader(shader_type)
    GL.glShaderSource(sh, source)
    GL.glCompileShader(sh)
    if not GL.glGetShaderiv(sh, GL.GL_COMPILE_STATUS):
        log = GL.glGetShaderInfoLog(sh)
        GL.glDeleteShader(sh)
        raise RuntimeError(f"Shader 编译失败: {log}")
    return sh


def _link_program(vs_src: str, fs_src: str) -> int:
    prog = GL.glCreateProgram()
    vs = _compile_shader(GL.GL_VERTEX_SHADER, vs_src)
    fs = _compile_shader(GL.GL_FRAGMENT_SHADER, fs_src)
    GL.glAttachShader(prog, vs)
    GL.glAttachShader(prog, fs)
    # 显式绑定顶点属性位置（与 GpuMesh 的 VAO 布局一致），避免链接器错位
    GL.glBindAttribLocation(prog, 0, "in_position")
    GL.glBindAttribLocation(prog, 1, "in_normal")
    GL.glBindAttribLocation(prog, 2, "in_uv")
    GL.glBindAttribLocation(prog, 3, "in_color")
    # 多输出（MRT）：fragColor→附件0（albedo/最终颜色），fragNormal→附件1（世界法线）
    GL.glBindFragDataLocation(prog, 0, "fragColor")
    GL.glBindFragDataLocation(prog, 1, "fragNormal")
    GL.glLinkProgram(prog)
    GL.glDeleteShader(vs)
    GL.glDeleteShader(fs)
    if not GL.glGetProgramiv(prog, GL.GL_LINK_STATUS):
        log = GL.glGetProgramInfoLog(prog)
        GL.glDeleteProgram(prog)
        raise RuntimeError(f"Program 链接失败: {log}")
    return prog


def _gl_off(offset: int):
    return ctypes.c_void_p(offset)


def _upload_texture(dds_bytes: bytes, srgb: bool = True, label: str = "", matid: bool = False, repeat: bool = False, tex_cache: dict | None = None) -> tuple[int, int]:
    """把 DDS 字节上传为 GL 压缩/未压缩纹理，返回 (纹理 id, GL_TEXTURE_* target)（失败返回 (0, GL_TEXTURE_2D)）。

    matid=True：materialIdMap（材质ID离散索引）用 NEAREST + 不生成 mip，避免边界插值出小数 ID 导致错乱索引；
    repeat=True：albedoArray/normalArray 用 REPEAT（官方 g_genericWrapSampler s5，u*scale 越界需 wrap 重复）；
    其余（materialIdMap/普通贴图）用 CLAMP_TO_EDGE，避免 REPEAT 在 UV 贴边界时对侧渗色。
    tex_cache：GL 纹理去重缓存（{key: (tex_id, target)}）。同一字节的贴图（如共享的
    CIT000_1k_ship_tiles_* 图集）在大量网格间复用 → 只上传一次，避免上千次重复上传
    占满 GPU/驱动内存。key = (id(dds_bytes), srgb, matid, repeat) —— id() 快且同一
    路径的 bytes 对象共享（geometry_service._texture_bytes_cache），可正确去重。
    """
    from models.dds_reader import parse_dds, GL_SRGB_RGBA8
    if tex_cache is not None:
        ck = (id(dds_bytes), srgb, matid, repeat)
        hit = tex_cache.get(ck)
        if hit is not None:
            return hit
    try:
        dds = parse_dds(dds_bytes)
    except Exception as exc:  # noqa: BLE001
        try:
            from app.signals import bus
            bus.log_message.emit(f"⚠️ 贴图解析失败{(' ' + label) if label else ''}: {exc}")
        except Exception:  # noqa: BLE001
            pass
        return (0, GL.GL_TEXTURE_2D)

    tex = GL.glGenTextures(1)
    is_array = dds.array_size > 1
    target = GL.GL_TEXTURE_2D_ARRAY if is_array else GL.GL_TEXTURE_2D
    _set_cache = True
    GL.glBindTexture(target, tex)

    if dds.bc_kind and dds.internal_format:
        # 压缩纹理：用 sRGB 内部格式上传，让 GPU 硬件逐 texel 解码（wows-toolkit 方案）
        fmt = dds.internal_format_srgb if srgb else dds.internal_format
        if is_array:
            n_mips = len(dds.layers or [])
            for i, leveldata in enumerate(dds.layers or []):
                w = max(dds.width >> i, 1)
                h = max(dds.height >> i, 1)
                GL.glCompressedTexImage3D(target, i, fmt, w, h, dds.array_size, 0, leveldata)
        else:
            n_mips = len(dds.mips)
            for i, mip in enumerate(dds.mips):
                w = max(dds.width >> i, 1)
                h = max(dds.height >> i, 1)
                GL.glCompressedTexImage2D(target, i, fmt, w, h, 0, mip)
        if matid:
            # materialIdMap：离散材质ID，强制 NEAREST（勿双线性，否则边界插值出小数ID→错乱索引）；
            # 不生成 mipmap（mip 高层会把邻近 ID 混合，产生错误材质）。
            GL.glTexParameteri(target, GL.GL_TEXTURE_MIN_FILTER, GL.GL_NEAREST)
            GL.glTexParameteri(target, GL.GL_TEXTURE_MAG_FILTER, GL.GL_NEAREST)
        else:
            # 无 mipmap：只用 base level 线性采样，避免近距 mip 层级跳变导致红→白/细缝
            GL.glTexParameteri(target, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
            GL.glTexParameteri(target, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
    else:
        # 未压缩 RGBA（BGR 字节序交换为 RGB，sRGB 内部格式硬件解码）
        if not dds.mips:
            GL.glDeleteTextures([tex])
            return (0, GL.GL_TEXTURE_2D)
        rgba = np.frombuffer(dds.mips[0], dtype=np.uint8).reshape(dds.height, dds.width, dds.rgba_bpp)
        if dds.rgba_bpp == 4:
            rgb = rgba[:, :, [2, 1, 0, 3]].copy()
        else:
            rgb = rgba[:, :, [2, 1, 0]].copy()
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL_SRGB_RGBA8 if srgb else GL.GL_RGBA8,
                        dds.width, dds.height, 0,
                        GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, np.ascontiguousarray(rgb))
        GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR_MIPMAP_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)

    _wrap = GL.GL_REPEAT if repeat else GL.GL_CLAMP_TO_EDGE
    GL.glTexParameteri(target, GL.GL_TEXTURE_WRAP_S, _wrap)
    GL.glTexParameteri(target, GL.GL_TEXTURE_WRAP_T, _wrap)
    GL.glBindTexture(target, 0)
    if tex_cache is not None and _set_cache:
        tex_cache[(id(dds_bytes), srgb, matid, repeat)] = (tex, target)
    return (tex, target)


def _emit_matrices(mesh) -> list:
    """返回该网格要绘制的模型矩阵序列（单体 = 一个；实例化 = 各节点矩阵）。

    提前算好并**只算一次**（模型矩阵在场景内不变），供逐实例 draw 复用，
    避免每帧对每个实例重复 `base @ inst` 矩阵乘。
    """
    insts = getattr(mesh, "instance_matrices", None) or []
    base = mesh.model_matrix
    if insts:
        if base is None:
            return insts
        return [np.ascontiguousarray(base @ inst, dtype=np.float32) for inst in insts]
    return [base]


def _find_normal_map(mtexs: dict | None) -> tuple[str, bytes]:
    """从材质声明的贴图集里找法线通道（稀疏材质：只认声明的 normal 属性）。

    返回 (path, bytes)；未声明返回 ("", b"")。绝不按名/前缀补全。
    """
    if not mtexs:
        return ("", b"")
    for k in ("g_normalMap", "normalMap", "normalArray"):
        v = mtexs.get(k)
        if v and v[1]:
            return v
    return ("", b"")


def _is_alpha_blend(mesh) -> bool:
    """是否走「透明/混合 pass」。

    grid、transparent：走透明 pass。
    meshdecal：**有 albedo 的**（g_albedoMap）走透明 pass（直显贴花，如 SHIP_MESHDECAL_ALBEDO_marking）；
    **仅 normal 的**（has_color=False 的 Normal-only decal，如 SHIP_MESHDECAL_NORMAL_tech）**不走**——
    它走独立的 Normal-only pass（只改 Normal，不输出颜色/Alpha，不参与颜色混合）。
    """
    if mesh.tech_family in ("grid", "transparent"):
        return True
    if mesh.tech_family == "decal":
        return bool(getattr(mesh, "has_color", True))
    return False


class GpuMesh:
    """上传到 GPU 的网格（VAO/VBO/IBO，可选贴图 + 模型矩阵 + 归属组件）。"""

    def __init__(self, name: str, positions: np.ndarray, normals: np.ndarray,
                 uvs: np.ndarray | None, colors: np.ndarray, indices: np.ndarray,
                 kind: str = "hull", texture_dds: bytes | None = None,
                 model_matrix: np.ndarray | None = None,
                 component: str | None = None,
                 armor_types: frozenset | None = None,
                 tech_family: str = "pbs",
                 material_textures: dict | None = None,
                 indexed_params: dict | None = None,
                 emissive_power: float | None = None,
                 is_wire: bool = False,
                 has_color: bool = True,
                 is_overlay: bool = False,
                 shape_names: list | None = None,
                 node_names: list | None = None,
                 instance_matrices: list | None = None,
                 tex_cache: dict | None = None):
        self.name = name
        self.kind = kind
        #: GL 纹理去重缓存（共享图集只上传一次；release 不删除缓存中的纹理）
        self._tex_cache = tex_cache
        #: 构成该网格的形状名与骨骼节点名（调试模式 3 标签用，替代材质/文件名）
        self.shape_names = list(shape_names or [])
        self.node_names = list(node_names or [])
        #: 逐节点实例矩阵（渲染空间 4x4 行主序）；非空时该网格是一份原始几何，
        #: 渲染时按其每个矩阵各画一次（多处实例）。model_matrix 恒等时直接用它。
        self.instance_matrices = [np.ascontiguousarray(m, dtype=np.float32)
                                  for m in (instance_matrices or [])]
        self.is_wire = is_wire
        #: 是否声明了颜色贴图（mfm 有 diffuseMap / indexed 有 albedoArray）。False=无色：
        #: 该材质不提供 Diffuse/Albedo 通道，但仍可提供声明的其他通道（如 normal）。
        self.has_color = has_color
        #: No-albedo 法线叠加层（稀疏材质：只声明 normal、未声明 diffuse）：
        #: 不跳过、不补默认色，走 u_mode==4 借用下层船体颜色。
        self.is_overlay = is_overlay
        #: 模型矩阵（行主序 4x4，渲染空间）；None = 恒等（舰体已在世界坐标）
        self.model_matrix = None if model_matrix is None else np.ascontiguousarray(model_matrix, dtype=np.float32)
        #: 装甲归属分类（kind='armor' 时用于按归属过滤显示）
        self.component = component
        #: 装甲类型（ArmorConstants.getArmorType 归属类型集合），用于类型过滤
        self.armor_types = armor_types or frozenset()
        #: shader 技术族（pbs/indexed/other）—— INDEXED 走分块渲染
        self.tech_family = tech_family
        self.emissive_power = emissive_power
        #: INDEXED 分块参数（tileIdxMatIdArr 数组、网格等）
        self.indexed_params = indexed_params
        n = positions.shape[0]
        vdata = np.empty((n, 12), dtype=np.float32)
        vdata[:, 0:3] = positions
        vdata[:, 3:6] = normals
        if uvs is not None and uvs.shape[0] == n:
            vdata[:, 6:8] = uvs
        else:
            vdata[:, 6:8] = 0.0
        vdata[:, 8:12] = colors
        self._vdata = np.ascontiguousarray(vdata)
        self._indices = np.ascontiguousarray(indices, dtype=np.uint32)
        self.index_count = int(indices.size)

        self._vbo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, self._vdata.nbytes, self._vdata, GL.GL_STATIC_DRAW)

        self._ibo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ELEMENT_ARRAY_BUFFER, self._ibo)
        GL.glBufferData(GL.GL_ELEMENT_ARRAY_BUFFER, self._indices.nbytes, self._indices, GL.GL_STATIC_DRAW)

        self._vao = GL.glGenVertexArrays(1)
        GL.glBindVertexArray(self._vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._vbo)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, GL.GL_FALSE, _VERTEX_STRIDE, _gl_off(_POS_OFFSET))
        GL.glEnableVertexAttribArray(1)
        GL.glVertexAttribPointer(1, 3, GL.GL_FLOAT, GL.GL_FALSE, _VERTEX_STRIDE, _gl_off(_NRM_OFFSET))
        GL.glEnableVertexAttribArray(2)
        GL.glVertexAttribPointer(2, 2, GL.GL_FLOAT, GL.GL_FALSE, _VERTEX_STRIDE, _gl_off(_UV_OFFSET))
        GL.glEnableVertexAttribArray(3)
        GL.glVertexAttribPointer(3, 4, GL.GL_FLOAT, GL.GL_FALSE, _VERTEX_STRIDE, _gl_off(_COL_OFFSET))
        GL.glBindBuffer(GL.GL_ELEMENT_ARRAY_BUFFER, self._ibo)
        GL.glBindVertexArray(0)

        self._texture = 0
        self._texture_target = GL.GL_TEXTURE_2D
        self.has_tex = False
        if texture_dds:
            # overlay（法线叠加层）的 texture_dds 是其声明的 normalMap：非 sRGB，
            # 避免 GPU 硬件 sRGB 解码把法线值改坏。
            tid, tgt = _upload_texture(texture_dds, srgb=(not is_overlay), label=self.name,
                                       tex_cache=self._tex_cache)
            if tid:
                self._texture = tid
                self._texture_target = tgt
                self.has_tex = True

        #: 额外贴图（INDEXED：materialIdMap/albedoArray/artMap 等）{键: GL 纹理 id}
        self._extra_tex: dict = {}
        if material_textures:
            for key, (_path, tbytes) in material_textures.items():
                # materialIdMap（材质ID）、albedoArray、normalArray、normalMap/g_normalMap
                # 均非 sRGB，避免 GPU 硬件 sRGB 解码造成双重 gamma（尤其法线）。
                _rep = key in ("albedoArray", "normalArray", "rgbNoiseMap")   # 官方 wrap 采样器
                _nsrgb = ("materialIdMap", "albedoArray", "normalArray", "normalMap", "g_normalMap")
                tid, _tgt = _upload_texture(tbytes, srgb=(key not in _nsrgb),
                                            label=_path or key, matid=(key == "materialIdMap"),
                                            repeat=_rep, tex_cache=self._tex_cache)
                if tid:
                    self._extra_tex[key] = tid

        self._line_ibo = None
        self._line_count = 0

    def _build_lines(self):
        if self._line_ibo is not None:
            return
        tri = self._indices.reshape(-1, 3)
        lines = np.empty((tri.shape[0], 6), dtype=np.uint32)
        lines[:, 0:2] = tri[:, [0, 1]]
        lines[:, 2:4] = tri[:, [1, 2]]
        lines[:, 4:6] = tri[:, [2, 0]]
        self._line_ibo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ELEMENT_ARRAY_BUFFER, self._line_ibo)
        GL.glBufferData(GL.GL_ELEMENT_ARRAY_BUFFER, lines.nbytes, np.ascontiguousarray(lines), GL.GL_STATIC_DRAW)
        self._line_count = int(lines.size)

    def render(self, mode: int, line: bool = False):
        ibo = self._line_ibo if line else self._ibo
        count = self._line_count if line else self.index_count
        if count == 0:
            return
        GL.glBindVertexArray(self._vao)
        GL.glBindBuffer(GL.GL_ELEMENT_ARRAY_BUFFER, ibo)
        GL.glDrawElements(mode, count, GL.GL_UNSIGNED_INT, None)
        GL.glBindVertexArray(0)

    def update_indices(self, indices: np.ndarray):
        """动态替换索引缓冲（可见性过滤/高亮重建，不重建 VBO/VAO）。"""
        idx = np.ascontiguousarray(indices, dtype=np.uint32)
        self._indices = idx
        self.index_count = int(idx.size)
        GL.glBindBuffer(GL.GL_ELEMENT_ARRAY_BUFFER, self._ibo)
        GL.glBufferData(GL.GL_ELEMENT_ARRAY_BUFFER, idx.nbytes, idx, GL.GL_DYNAMIC_DRAW)
        GL.glBindBuffer(GL.GL_ELEMENT_ARRAY_BUFFER, 0)
        # 索引变化后线框 IBO 失效
        if self._line_ibo is not None:
            GL.glDeleteBuffers(1, [self._line_ibo])
            self._line_ibo = None
            self._line_count = 0

    def release(self):
        try:
            GL.glDeleteVertexArrays(1, [self._vao])
            GL.glDeleteBuffers(2, [self._vbo, self._ibo])
            if self._line_ibo is not None:
                GL.glDeleteBuffers(1, [self._line_ibo])
            # 共享图集（在去重缓存中）不被释放，其他网格仍引用；只释放本网格独有的。
            cached = ({v[0] for v in self._tex_cache.values()}
                      if self._tex_cache else set())
            if self._texture and self._texture not in cached:
                GL.glDeleteTextures([self._texture])
            self._texture = 0
            if self._extra_tex:
                for tid in self._extra_tex.values():
                    if tid and tid not in cached:
                        GL.glDeleteTextures([tid])
                self._extra_tex = {}
        except Exception:  # noqa: BLE001
            pass


class GeometryViewport(QOpenGLWidget):
    """3D 视口（PyOpenGL）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._camera = OrbitCamera()
        self._program = 0            # 单输出（单 drawbuffer 目标用）
        self._uniforms = {}
        self._program_mrt = 0        # 双输出（scene_fbo MRT，Pass1 用）
        self._uniforms_mrt = {}
        self._fs_program = 0
        self._fs_uniforms = {}
        self._meshes: list[GpuMesh] = []
        self._mesh_specs: list[dict] = []
        self._scene_bounds = None
        self._show_hull = True
        self._show_mounts = True
        self._show_armor = True
        self._wireframe = False
        #: GL 纹理去重缓存（同一字节图集只上传一次；release 不删除缓存中的纹理）
        #: 在 initializeGL 创建上下文时重置（旧上下文纹理 id 失效）。
        self._gl_tex_cache: dict = {}
        #: 装甲归属过滤：None/空 = 全部显示；否则仅显示集合内的 component
        self._armor_components: set | None = None
        #: 装甲类型过滤（ArmorConstants 归属类型）：None/空 = 全部
        self._armor_types: set | None = None
        self._auto_frame = True
        self._needs_rebuild = False
        self._last_pos: QPoint | None = None
        # ── 装甲场景（重构后：世界空间三角形汤聚合） ──
        self._armor_scene = None              # ArmorScene | None
        self._armor_gpu: GpuMesh | None = None     # 聚合装甲网格（渲染空间）
        self._edge_gpu: GpuMesh | None = None      # 板块边界线
        self._hl_gpu: GpuMesh | None = None        # 高亮覆盖网格（按需重建）
        self._hl_color: tuple = HIGHLIGHT_HOVER
        self._visible_tris: np.ndarray | None = None   # (T,) bool，None=全可见
        self._armor_opacity: float = 1.0
        self._show_edges: bool = True
        # ── 离屏 FBO（稀疏材质 normal 叠加层复用下层船体颜色） ──
        self._scene_fbo: int = 0
        self._scene_color_tex: int = 0
        self._scene_normal_tex: int = 0
        self._scene_depth_rb: int = 0
        self._scene_fbo_size = (0, 0)
        # Normal Ping-Pong FBO（独立，避免 feedback loop）
        self._na_fbo: int = 0; self._na_tex: int = 0
        self._nb_fbo: int = 0; self._nb_tex: int = 0
        self._fullscreen_vao: int = 0; self._fullscreen_vbo: int = 0
        #: Debug 模式（N 循环）：0=关，1=最终法线显色，2=挂载点位+名称，3=所有模型名称
        self._debug_mode = 0
        #: debug(2/3) 模型点位名称（paintEvent 叠加文本）
        self._mount_labels = []
        #: GL 上下文是否已就绪（initializeGL 后）；未就绪的重建操作延迟到 paintGL
        self._gl_ready: bool = False
        self._vis_pending: bool = False
        self._hl_pending: bool = False
        self._hover_tri: int | None = None
        self._selected_plate: tuple | None = None
        self._last_pick_time: float = 0.0
        self._press_pos: QPoint | None = None
        #: 交互回调（viewer 设置）：on_hover(tri_idx|None, QPoint全局坐标)
        self.on_hover = None
        #: on_select(plate_key|None)
        self.on_select = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(480, 360)

    # ── 场景设置 ─────────────────────────────────────────

    def set_scene(self, ship_geometry, show_hull: bool = True, show_armor: bool = True,
                  armor_scene=None):
        """加载舰船场景：舰体分段 + 挂载模型（各自独立贴图/变换）+ 装甲。

        armor_scene：ArmorScene 聚合场景（重构后装甲渲染/拾取数据源）。
        传入时装甲改由场景渲染（跳过逐 ArmorMesh 的 spec 路径）。
        """
        # 新场景：重置贴图去重缓存（避免跨场景 id() 复用命中陈旧纹理；
        # 场景内共享图集仍只上传一次）
        self._gl_tex_cache = {}
        specs = []
        if ship_geometry is not None:
            tex = ship_geometry.texture_dds if ship_geometry.texture_dds else None
            white = (1.0, 1.0, 1.0, 1.0)
            for hm in ship_geometry.hull_meshes:
                # 按材质拆分的分段使用自己的贴图（如 DeckHouse），否则用舰体默认贴图
                # crack/damage 损伤网格不显示（导出保留用）
                if getattr(hm, "is_crack", False):
                    continue
                has_color = getattr(hm, "has_color", True)
                mtexs = getattr(hm, "material_textures", None) or {}
                # 稀疏材质：No-albedo 但声明了 normal 的 mesh → 法线叠加层，主贴图绑定其
                # 声明的 normalMap（不补默认色、不跳过、颜色借用下层船体 FBO）。
                if not has_color:
                    _np, _nb = _find_normal_map(mtexs)
                    hm_tex = _nb if _nb else None
                else:
                    hm_tex = getattr(hm, "texture_dds", None) or tex
                specs.append({
                    "name": hm.name, "kind": "hull",
                    "positions": hm.positions, "normals": hm.normals, "uvs": hm.uvs,
                    "colors": np.full((hm.positions.shape[0], 4), white, dtype=np.float32),
                    "indices": hm.indices, "texture": hm_tex,
                    "tech_family": getattr(hm, "tech_family", "pbs"),
                    "material_textures": getattr(hm, "material_textures", None),
                    "indexed_params": getattr(hm, "indexed_params", None),
                    "emissive_power": getattr(hm, "emissive_power", None),
                    "is_wire": getattr(hm, "is_wire", False),
                    "has_color": has_color,
                    "is_overlay": (not has_color),
                    "shape_names": getattr(hm, "shape_names", None),
                    "node_names": getattr(hm, "node_names", None),
                    "instance_matrices": getattr(hm, "instance_matrices", None),
                })
            for mm in ship_geometry.mounts:
                # crack/damage 损伤网格不显示（导出保留用）
                if getattr(mm, "is_crack", False):
                    continue
                has_color = getattr(mm, "has_color", True)
                mtexs = getattr(mm, "material_textures", None) or {}
                # 稀疏材质：No-albedo 但声明 normal → 法线叠加层（同船体）。
                if not has_color:
                    _np, _nb = _find_normal_map(mtexs)
                    mm_tex = _nb if _nb else None
                else:
                    mm_tex = mm.texture_dds if mm.texture_dds else tex
                specs.append({
                    "name": mm.name, "kind": "mount",
                    "positions": mm.positions, "normals": mm.normals, "uvs": mm.uvs,
                    "colors": np.full((mm.positions.shape[0], 4), white, dtype=np.float32),
                    "indices": mm.indices,
                    "texture": mm_tex,
                    "model": mm.model_matrix,
                    "tech_family": getattr(mm, "tech_family", "pbs"),
                    "material_textures": getattr(mm, "material_textures", None),
                    "indexed_params": getattr(mm, "indexed_params", None),
                    "emissive_power": getattr(mm, "emissive_power", None),
                    "is_wire": getattr(mm, "is_wire", False),
                    "has_color": has_color,
                    "is_overlay": (not has_color),
                    "shape_names": getattr(mm, "shape_names", None),
                    "node_names": getattr(mm, "node_names", None),
                    "instance_matrices": getattr(mm, "instance_matrices", None),
                })
            if armor_scene is None:
                # 旧路径：逐 ArmorMesh spec（无聚合场景时的兼容渲染）
                for am in ship_geometry.armor_meshes:
                    atypes = frozenset()
                    from models.collision_materials import get_armor_types
                    for tri in am.triangles:
                        atypes |= get_armor_types(tri.material_name)
                    specs.append({
                        "name": am.name, "kind": "armor",
                        "positions": am.positions, "normals": am.normals, "uvs": None,
                        "colors": am.colors, "indices": am.indices, "texture": None,
                        "model": am.model_matrix, "component": am.component,
                        "armor_types": atypes,
                    })
            if ship_geometry.bounds_min is not None:
                self._scene_bounds = (ship_geometry.bounds_center, ship_geometry.bounds_size)
        self._mesh_specs = specs
        self._armor_scene = armor_scene
        self._visible_tris = None
        self._hover_tri = None
        self._selected_plate = None
        self._show_hull = show_hull
        self._show_armor = show_armor
        self._auto_frame = True
        # GL 调用必须在上下文激活时执行（initializeGL/paintGL 内），这里只登记重建标记
        self._needs_rebuild = True
        self.update()

    def _build_meshes(self):
        for m in self._meshes:
            m.release()
        self._meshes = []
        for spec in self._mesh_specs:
            # 解析空间 → 渲染空间（右手系，与 glTF 同构）变换。
            # ⚠️ 与导出服务共用 prepare_render_mesh（models/geometry_transform.py），
            # 保证「查看器里看到的 = 导出的」；该函数内置法线朝向修正与绕序混合拆分。
            p, n, idx, uvs0, colors0 = prepare_render_mesh(
                spec["positions"], spec["normals"], spec["indices"],
                spec["colors"], spec.get("uvs"))
            mesh = GpuMesh(
                name=spec["name"], kind=spec["kind"],
                positions=p, normals=n, uvs=uvs0,
                colors=colors0,
                indices=np.ascontiguousarray(idx, dtype=np.uint32),
                texture_dds=spec.get("texture"),
                model_matrix=spec.get("model"),
                component=spec.get("component"),
                armor_types=spec.get("armor_types"),
                tech_family=spec.get("tech_family", "pbs"),
                material_textures=spec.get("material_textures"),
                indexed_params=spec.get("indexed_params"),
                emissive_power=spec.get("emissive_power"),
                is_wire=spec.get("is_wire", False),
                has_color=spec.get("has_color", True),
                is_overlay=spec.get("is_overlay", False),
                shape_names=spec.get("shape_names"),
                node_names=spec.get("node_names"),
                instance_matrices=spec.get("instance_matrices"),
                tex_cache=self._gl_tex_cache,
            )
            self._meshes.append(mesh)

        # ── 装甲场景聚合网格（重构后路径） ──
        self._release_armor_gpu()
        if self._armor_scene is not None and self._armor_scene.tri_count:
            self._build_armor_gpu()

    def _build_armor_gpu(self):
        """由 ArmorScene 构建聚合装甲网格 + 边界线网格（渲染空间：Z 镜像）。"""
        sc = self._armor_scene
        # 渲染空间：世界坐标 Z 取反（与 _build_meshes 的镜像一致）
        mirror = np.array([1.0, 1.0, -1.0], dtype=np.float32)
        pos = np.ascontiguousarray(sc.world_positions * mirror)
        # 法线：Z 镜像后需翻转 Z 分量（位置镜像 det=-1）
        nrm = np.ascontiguousarray(sc.world_normals * mirror)
        col = np.ascontiguousarray(sc.colors, dtype=np.float32)
        idx = np.arange(sc.tri_count * 3, dtype=np.uint32)
        self._armor_gpu = GpuMesh(
            name="armor_scene", kind="armor_scene",
            positions=pos, normals=nrm, uvs=None, colors=col, indices=idx,
        )
        # 边界线：端点对 → 渲染空间坐标，索引为顺序对
        if sc.edge_positions.shape[0]:
            epos = np.ascontiguousarray(sc.edge_positions * mirror)
            enrm = np.zeros_like(epos)
            ecol = np.full((epos.shape[0], 4), PLATE_EDGE_COLOR, dtype=np.float32)
            eidx = np.arange(epos.shape[0], dtype=np.uint32)
            self._edge_gpu = GpuMesh(
                name="armor_edges", kind="armor_edge",
                positions=epos, normals=enrm, uvs=None, colors=ecol, indices=eidx,
            )

    def _release_armor_gpu(self):
        for attr in ("_armor_gpu", "_edge_gpu", "_hl_gpu"):
            m = getattr(self, attr)
            if m is not None:
                m.release()
                setattr(self, attr, None)

    def clear_scene(self):
        self._mesh_specs = []
        self._scene_bounds = None
        self._armor_scene = None
        self._needs_rebuild = True
        self.update()

    # ── 显示选项 ─────────────────────────────────────────

    def set_view_options(self, show_hull=None, show_armor=None, wireframe=None,
                         show_mounts=None, armor_components=None, armor_types=None):
        if show_hull is not None:
            self._show_hull = bool(show_hull)
        if show_armor is not None:
            self._show_armor = bool(show_armor)
            # 船体/装甲互斥：装甲开启时隐藏船体与挂载；关闭时恢复船体/挂载
            # （仅当未同时显式设置 show_hull 时恢复，避免覆盖调用方意图）
            if self._show_armor:
                self._show_hull = False
                self._show_mounts = False
            elif show_hull is None:
                self._show_hull = True
                self._show_mounts = True
        if show_mounts is not None:
            self._show_mounts = bool(show_mounts)
        if wireframe is not None:
            self._wireframe = bool(wireframe)
        if armor_components is not None:
            # None = 全部；否则为可见归属集合
            self._armor_components = set(armor_components) if armor_components else None
        if armor_types is not None:
            self._armor_types = set(armor_types) if armor_types else None
        self.update()

    # ── 装甲场景显示控制（重构后） ─────────────────────

    def set_armor_display(self, opacity=None, show_edges=None):
        """装甲显示选项：不透明度 / 板块描边。"""
        if opacity is not None:
            self._armor_opacity = float(np.clip(opacity, 0.05, 1.0))
        if show_edges is not None:
            self._show_edges = bool(show_edges)
        self.update()

    def set_visible_tris(self, visible_tris):
        """设置装甲三角形可见掩码（(T,) bool；None=全部可见）。"""
        self._visible_tris = visible_tris
        if not self._run_gl(self._apply_visibility):
            self._vis_pending = True
        self.update()

    def select_plate(self, plate_key):
        """选中板块（plate_key=(zone, mat, tenths)；None=取消），重建高亮。"""
        self._selected_plate = plate_key
        self._hl_color = HIGHLIGHT_SELECT if plate_key is not None else HIGHLIGHT_HOVER
        if not self._run_gl(self._rebuild_highlight):
            self._hl_pending = True
        self.update()

    def _run_gl(self, fn):
        """在 GL 上下文内执行 GL 依赖的重建操作。

        GL 未就绪（initializeGL 前）返回 False，由调用方置 pending 标记，
        在 paintGL 首帧补做；避免在上下文外上传缓冲产生未定义内容。
        """
        if not self._gl_ready:
            return False
        self.makeCurrent()
        try:
            fn()
        finally:
            self.doneCurrent()
        return True

    def _flush_pending_gl(self):
        """在 paintGL/initializeGL 内补做上下文外登记的重建操作。"""
        if self._vis_pending:
            self._apply_visibility()
            self._vis_pending = False
        if self._hl_pending:
            self._rebuild_highlight()
            self._hl_pending = False

    def _apply_visibility(self):
        """按可见掩码重建装甲/边界线索引缓冲。"""
        if self._armor_gpu is None or self._armor_scene is None:
            return
        sc = self._armor_scene
        vis = self._visible_tris
        if vis is None:
            idx = np.arange(sc.tri_count * 3, dtype=np.uint32)
        else:
            idx = (np.nonzero(vis)[0][:, None] * 3
                   + np.arange(3, dtype=np.uint32)).ravel().astype(np.uint32)
        self._armor_gpu.update_indices(idx)
        # 边界线：任一侧三角形可见即显示
        if self._edge_gpu is not None and sc.edge_positions.shape[0]:
            if vis is None:
                eidx = np.arange(sc.edge_positions.shape[0], dtype=np.uint32)
            else:
                t1, t2 = sc.edge_tris[:, 0], sc.edge_tris[:, 1]
                keep = np.zeros(sc.edge_tris.shape[0], dtype=bool)
                k1 = t1 >= 0
                k2 = t2 >= 0
                keep[k1] |= vis[t1[k1]]
                keep[k2] |= vis[t2[k2]]
                eidx = (np.nonzero(keep)[0][:, None] * 2
                        + np.arange(2, dtype=np.uint32)).ravel().astype(np.uint32)
            self._edge_gpu.update_indices(eidx)

    def _rebuild_highlight(self):
        """按选中板块重建高亮覆盖网格（沿法线微偏移防 z-fighting）。"""
        if self._hl_gpu is not None:
            self._hl_gpu.release()
            self._hl_gpu = None
        if self._selected_plate is None or self._armor_scene is None \
                or self._armor_gpu is None:
            return
        tris = self._armor_scene.tris_for_plate(self._selected_plate)
        if not len(tris):
            return
        tris = np.asarray(tris, dtype=np.int64)
        sc = self._armor_scene
        mirror = np.array([1.0, 1.0, -1.0], dtype=np.float32)
        p = sc.world_positions[tris[:, None] * 3 + np.arange(3)].reshape(-1, 3)
        n = sc.world_normals[tris[:, None] * 3 + np.arange(3)].reshape(-1, 3)
        pos = np.ascontiguousarray((p + n * 0.02) * mirror)
        nrm = np.ascontiguousarray(n * mirror)
        col = np.full((pos.shape[0], 4), self._hl_color, dtype=np.float32)
        idx = np.arange(pos.shape[0], dtype=np.uint32)
        self._hl_gpu = GpuMesh(
            name="armor_highlight", kind="armor_hl",
            positions=pos, normals=nrm, uvs=None, colors=col, indices=idx,
        )

    def pick_at(self, x: int, y: int):
        """屏幕坐标 → 射线拾取。返回 (tri_idx, ArmorTriangleInfo) 或 None。"""
        sc = self._armor_scene
        if sc is None or not sc.tri_count or self.width() < 2:
            return None
        aspect = self.width() / max(self.height(), 1)
        inv_vp = np.linalg.inv(
            self._camera.projection_matrix(aspect) @ self._camera.view_matrix())
        ndcx = 2.0 * x / self.width() - 1.0
        ndcy = 1.0 - 2.0 * y / max(self.height(), 1)

        def _unproj(z):
            v = inv_vp @ np.array([ndcx, ndcy, z, 1.0], dtype=np.float64)
            return v[:3] / v[3]

        p0, p1 = _unproj(0.0), _unproj(1.0)
        d = p1 - p0
        d /= (np.linalg.norm(d) + 1e-12)
        # ArmorScene 为未镜像船体空间 → 射线 Z 取反
        ro = p0 * np.array([1.0, 1.0, -1.0])
        rd = d * np.array([1.0, 1.0, -1.0])
        ti = sc.ray_pick(ro, rd, self._visible_tris)
        if ti is None:
            return None
        return int(ti), sc.tri_info[int(ti)]

    def camera(self) -> OrbitCamera:
        return self._camera

    def _frame_camera(self):
        if self._scene_bounds is None:
            return
        center, size = self._scene_bounds
        self._camera.frame(center, size, self.width(), max(self.height(), 1))

    # ── OpenGL 生命周期 ─────────────────────────────────

    def initializeGL(self):
        # 新上下文：旧纹理 id 失效，重置贴图去重缓存
        self._gl_tex_cache = {}
        # 单输出 program：用于单 drawbuffer 目标（decal normal pass / 默认 FBO / 全屏）。
        # 若仍用双输出 FRAG_SRC，会在只有 1 个 drawbuffer 上触发 GL_INVALID_OPERATION(1282)。
        self._program = _link_program(VERT_SRC, FRAG_SRC_SINGLE)
        for name in _UNIFORMS:
            self._uniforms[name] = GL.glGetUniformLocation(self._program, name)
        # MRT program（fragColor + fragNormal 双输出）：仅 Pass1 渲 scene_fbo(RT0/RT1) 用。
        self._program_mrt = _link_program(VERT_SRC, FRAG_SRC)
        self._uniforms_mrt = {name: GL.glGetUniformLocation(self._program_mrt, name)
                              for name in _UNIFORMS}
        # 独立 fullscreen program（gl_VertexID 全屏三角形，无 VAO/attrib；单输出）
        self._fs_program = _link_program(TEX_VERT_SRC, FRAG_SRC_SINGLE)
        self._fs_uniforms = {name: GL.glGetUniformLocation(self._fs_program, name)
                             for name in ("u_mode", "u_viewport", "u_scene_tex",
                                          "u_scene_normal_tex", "u_scene_final_tex",
                                          "u_light_dir", "u_ambient")}
        GL.glEnable(GL.GL_DEPTH_TEST)
        self._gl_ready = True
        self._build_meshes()
        self._needs_rebuild = False
        self._flush_pending_gl()
        if self._auto_frame:
            self._frame_camera()

    def resizeGL(self, w, h):
        GL.glViewport(0, 0, w, h)

    def paintGL(self):
        w, h = self.width(), max(self.height(), 1)
        GL.glViewport(0, 0, w, h)
        GL.glClearColor(0.10, 0.12, 0.15, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
        # 每帧重设默认 GL 状态（防御上一帧遗留的 depth/blend 被调试覆盖层破坏）
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glDepthMask(GL.GL_TRUE)
        GL.glDisable(GL.GL_BLEND)
        GL.glDepthFunc(GL.GL_LESS)

        # 上下文已激活，执行挂起的网格重建/取景
        if self._needs_rebuild and self._program:
            self._build_meshes()
            self._needs_rebuild = False
            if self._auto_frame:
                self._frame_camera()
        self._flush_pending_gl()

        if not self._meshes or not self._program:
            return

        # 按当前相机距离动态收紧 near/far，提升深度精度，避免远处薄面 z-fighting
        cam = self._camera
        radius = float(np.linalg.norm(self._scene_bounds[1])) * 0.5 if self._scene_bounds else 1.0
        cam.near = max(cam.distance - radius * 2.0, 0.05)
        cam.far = cam.distance + radius * 4.0

        aspect = w / h
        view = cam.view_matrix()
        proj = cam.projection_matrix(aspect)

        GL.glUseProgram(self._program)
        u = self._uniforms
        GL.glUniform3f(u["u_light_dir"], 0.35, 0.6, 0.72)
        # 环境光从 0.30 调低到 0.12：半兰伯特原本光照范围仅 [0.65,1.0]，把法线扰动压得几乎不可见；
        # 降低 ambient 让方向光占主导，以凸显法线贴图(indicated 凹凸)细节，便于验证法线是否生效。
        GL.glUniform3f(u["u_ambient"], 0.12, 0.12, 0.14)

        try:
            # ── deferred Normal Accumulation ──
            # decal_tech(Normal-only) 走独立 pass；有 albedo 的 decal 走透明 pass
            decal_overlays = [m for m in self._meshes
                              if getattr(m, "is_overlay", False)
                              and not getattr(m, "has_color", True)]
            # 始终走 deferred 管线（有网格即用），debug(1) 展示最终法线
            use_surface = bool(self._meshes)
            if use_surface:
                use_surface = self._ensure_scene_fbo(w, h)
            # Pass1：Hull → scene_fbo[RT0=Albedo, RT1=Hull Normal, Depth]
            if use_surface:
                GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self._scene_fbo)
                GL.glViewport(0, 0, w, h)
                GL.glClearColor(0.10, 0.12, 0.15, 1.0)
                GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
                GL.glDrawBuffers([GL.GL_COLOR_ATTACHMENT0, GL.GL_COLOR_ATTACHMENT1])
                GL.glDisable(GL.GL_BLEND)
                GL.glDepthMask(GL.GL_TRUE)
                # MRT 需双输出 program；用独立 _uniforms_mrt（与 _program 的单输出分离）
                GL.glUseProgram(self._program_mrt)
                um = self._uniforms_mrt
                GL.glUniform3f(um["u_light_dir"], 0.35, 0.6, 0.72)
                GL.glUniform3f(um["u_ambient"], 0.12, 0.12, 0.14)
                GL.glUniform1i(um["u_mrt"], 1)
                GL.glUniform1i(um["u_use_scene_normal"], 0)
                self._draw_ship_solid(view, proj, um, mrt_surface=True)
                # 切回单输出 _program（后续 PassA/B/C 均只渲 1 个 drawbuffer）
                GL.glUseProgram(self._program)
                # PassA：fullscreen quad 把 Hull Normal(scene_normal_tex) 拷到 normal_a
                GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self._na_fbo)
                GL.glViewport(0, 0, w, h)
                GL.glDrawBuffers([GL.GL_COLOR_ATTACHMENT0])
                GL.glDisable(GL.GL_BLEND)
                GL.glDisable(GL.GL_DEPTH_TEST)
                GL.glUniform1i(u["u_mode"], 10)
                GL.glUniform2f(u["u_viewport"], float(w), float(h))
                GL.glActiveTexture(GL.GL_TEXTURE1)
                GL.glBindTexture(GL.GL_TEXTURE_2D, self._scene_normal_tex)
                GL.glActiveTexture(GL.GL_TEXTURE0)
                GL.glUniform1i(u["u_mrt"], 0)
                self._draw_fullscreen(10, w, h)
            # PassB：normal_b 始终以 Hull Normal 为底（全屏拷贝避免虚影），有 decal 再合成
            if use_surface:
                GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self._nb_fbo)
                GL.glViewport(0, 0, w, h)
                GL.glDrawBuffers([GL.GL_COLOR_ATTACHMENT0])
                GL.glDisable(GL.GL_BLEND)
                # ★ 先用全屏拷贝把 Hull Normal(na_tex) 填入 normal_b 作底，避免未覆盖处残留
                #   上一帧数据产生「虚影延迟」；之后 decal 只在其覆盖处覆盖合成法线。
                GL.glDisable(GL.GL_DEPTH_TEST)
                GL.glUniform1i(u["u_mrt"], 0)
                GL.glUniform1i(u["u_mode"], 10)
                GL.glUniform2f(u["u_viewport"], float(w), float(h))
                GL.glActiveTexture(GL.GL_TEXTURE1)
                GL.glBindTexture(GL.GL_TEXTURE_2D, self._na_tex)
                GL.glUniform1i(u["u_scene_normal_tex"], 1)
                GL.glActiveTexture(GL.GL_TEXTURE0)
                self._draw_fullscreen(10, w, h)
                if decal_overlays:
                    # 接着合成 decal（深度遮挡：只写船体表面，深度来自 scene_depth）
                    GL.glEnable(GL.GL_DEPTH_TEST)
                    GL.glDepthFunc(GL.GL_LEQUAL)
                    GL.glDepthMask(GL.GL_FALSE)
                    GL.glDisable(GL.GL_BLEND)
                    GL.glUniform1i(u["u_mrt"], 0)
                    GL.glUniform1i(u["u_mode"], 9)
                    GL.glUniform1i(u["u_use_scene_normal"], 0)
                    GL.glUniform2f(u["u_viewport"], float(w), float(h))
                    GL.glActiveTexture(GL.GL_TEXTURE1)
                    GL.glBindTexture(GL.GL_TEXTURE_2D, self._na_tex)
                    GL.glUniform1i(u["u_scene_normal_tex"], 1)
                    GL.glActiveTexture(GL.GL_TEXTURE0)
                    for mesh in decal_overlays:
                        # 逐实例绘制（每实例 bind 材质 + 更新模型矩阵）
                        insts = getattr(mesh, "instance_matrices", None) or []
                        if insts:
                            base = mesh.model_matrix
                            for inst in insts:
                                model = (inst if base is None
                                         else np.ascontiguousarray(base @ inst, dtype=np.float32))
                                self._draw_decal_once(view, proj, u, mesh, model)
                        else:
                            self._draw_decal_once(view, proj, u, mesh, mesh.model_matrix)
                    self._apply_model(view, proj, None, u)
                    GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
                    GL.glDepthMask(GL.GL_TRUE)
                    GL.glDepthFunc(GL.GL_LESS)
            # PassC：最终 lighting（fullscreen quad 读 Albedo + Final Normal）→ 默认 FBO
            dflt = self.defaultFramebufferObject()
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, dflt)
            GL.glViewport(0, 0, w, h)
            GL.glDisable(GL.GL_BLEND)
            # 显式把默认 FBO 的 drawbuffer 设为单个附件0，避免残留的多 attachment
            # 状态导致「fragment 输出 > drawbuffer」的 GL_INVALID_OPERATION(1282)
            GL.glDrawBuffers([GL.GL_COLOR_ATTACHMENT0])
            GL.glDepthMask(GL.GL_FALSE)
            GL.glDisable(GL.GL_DEPTH_TEST)
            GL.glUniform1i(u["u_use_scene_normal"], 0)
            if use_surface:
                # debug(1)：直接显色最终法线（normal_b = Hull+Decal 合成）
                if self._debug_mode == 1:
                    GL.glUniform1i(u["u_mode"], 12)
                    GL.glUniform2f(u["u_viewport"], float(w), float(h))
                    GL.glActiveTexture(GL.GL_TEXTURE8)
                    GL.glBindTexture(GL.GL_TEXTURE_2D, self._nb_tex)
                    GL.glUniform1i(u["u_scene_final_tex"], 8)
                    GL.glActiveTexture(GL.GL_TEXTURE0)
                    self._draw_fullscreen(12, w, h)
                else:
                    # 最终 Lighting：读 Hull Albedo + Final Normal
                    GL.glUniform1i(u["u_mode"], 11)
                    GL.glUniform2f(u["u_viewport"], float(w), float(h))
                    GL.glActiveTexture(GL.GL_TEXTURE5)
                    GL.glBindTexture(GL.GL_TEXTURE_2D, self._scene_color_tex)
                    GL.glUniform1i(u["u_scene_tex"], 5)
                    GL.glActiveTexture(GL.GL_TEXTURE8)
                    GL.glBindTexture(GL.GL_TEXTURE_2D, self._nb_tex)
                    GL.glUniform1i(u["u_scene_final_tex"], 8)
                    GL.glActiveTexture(GL.GL_TEXTURE0)
                    self._draw_fullscreen(11, w, h)
            # ★ 把 scene 深度拷到默认 FBO：透明 pass（玻璃/线网/螺旋桨等）深度测试需要
            #   船体深度，否则全过 → 模型穿透显示。仅 deferred 路径有 scene 深度。
            if use_surface:
                GL.glDepthMask(GL.GL_TRUE)   # 全屏光照后 mask=FALSE，会抑制 depth blit
                GL.glBindFramebuffer(GL.GL_READ_FRAMEBUFFER, self._scene_fbo)
                GL.glBindFramebuffer(GL.GL_DRAW_FRAMEBUFFER, dflt)
                GL.glBlitFramebuffer(0, 0, w, h, 0, 0, w, h,
                                     GL.GL_DEPTH_BUFFER_BIT, GL.GL_NEAREST)
                GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, dflt)

            # ── 透明 pass（grid_alpha 线网 / glass / propeller / water / cloud 等） ──
            # 贴图 alpha 通道即透明度（线网/玻璃/螺旋桨/水），开启混合；
            # 无光照保持贴图原色，不写深度避免自身双面重叠 z-fight，
            # 船体深度已 blit 到默认 FBO，故开启深度测试让被遮挡处被剔除（否则穿透显示）。
            GL.glEnable(GL.GL_BLEND)
            GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
            GL.glDepthMask(GL.GL_FALSE)
            GL.glEnable(GL.GL_DEPTH_TEST)
            GL.glDepthFunc(GL.GL_LEQUAL)
            GL.glUniform1i(u["u_mode"], 2)
            GL.glUniform1f(u["u_emissive"], 0.0)
            GL.glUniform1f(u["u_opacity"], 1.0)
            for mesh in self._meshes:
                if mesh.kind not in ("hull", "mount"):
                    continue
                if not _is_alpha_blend(mesh):
                    continue
                if mesh.kind == "hull" and (not self._show_hull or self._show_armor):
                    continue
                if mesh.kind == "mount" and (not self._show_mounts or self._show_armor):
                    continue
                if mesh.tech_family == "decal" and not getattr(mesh, "has_color", True):
                    continue   # decal_tech 是法线细节层：其法线已写入 Final Normal，不再输出颜色
                GL.glUniform1i(u["u_mode"], 2)   # grid/glass/albedo-decal 无光照直显
                # 逐实例绘制（每实例 bind 材质 + 更新模型矩阵）
                insts = getattr(mesh, "instance_matrices", None) or []
                if insts:
                    base = mesh.model_matrix
                    for inst in insts:
                        model = (inst if base is None
                                 else np.ascontiguousarray(base @ inst, dtype=np.float32))
                        self._draw_alpha_once(view, proj, u, mesh, model)
                else:
                    self._draw_alpha_once(view, proj, u, mesh, mesh.model_matrix)
            self._apply_model(view, proj, None, u)
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
            GL.glDisable(GL.GL_BLEND)
            GL.glDepthMask(GL.GL_TRUE)

            # ── 装甲 pass ──
            if self._show_armor:
                GL.glUniform1i(u["u_has_tex"], 0)
                GL.glEnable(GL.GL_POLYGON_OFFSET_FILL)
                GL.glPolygonOffset(-1.0, -1.0)   # 装甲略微拉向相机，避免与船体 z-fight
                GL.glEnable(GL.GL_BLEND)
                GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
                GL.glDepthMask(GL.GL_TRUE)
                GL.glDepthFunc(GL.GL_LEQUAL)
                if self._armor_scene is not None and self._armor_gpu is not None:
                    # 重构后：聚合装甲场景（平涂色 + 不透明度）
                    GL.glUniform1i(u["u_mode"], 2)
                    GL.glUniform1f(u["u_opacity"], self._armor_opacity)
                    self._apply_model(view, proj, None)
                    self._armor_gpu.render(GL.GL_TRIANGLES)
                    GL.glUniform1f(u["u_opacity"], 1.0)
                    GL.glUniform1i(u["u_mode"], 0)
                else:
                    # 旧路径：逐 ArmorMesh
                    for mesh in self._meshes:
                        if mesh.kind != "armor":
                            continue
                        if self._armor_components is not None and \
                                mesh.component not in self._armor_components:
                            continue
                        if self._armor_types is not None and \
                                not (mesh.armor_types & self._armor_types):
                            continue
                        self._apply_model(view, proj, mesh.model_matrix)
                        mesh.render(GL.GL_TRIANGLES)
                self._apply_model(view, proj, None)
                GL.glDisable(GL.GL_BLEND)
                GL.glDepthFunc(GL.GL_LESS)
                GL.glDisable(GL.GL_POLYGON_OFFSET_FILL)
                GL.glDepthMask(GL.GL_TRUE)

                # ── 板块边界描边 pass（装甲场景模式） ──
                if self._armor_scene is not None and self._edge_gpu is not None \
                        and self._show_edges and self._edge_gpu.index_count:
                    GL.glDisable(GL.GL_BLEND)
                    GL.glDepthMask(GL.GL_FALSE)
                    GL.glEnable(GL.GL_POLYGON_OFFSET_FILL)
                    GL.glPolygonOffset(-2.0, -2.0)
                    GL.glUniform1i(u["u_mode"], 2)
                    GL.glUniform1f(u["u_opacity"], PLATE_EDGE_COLOR[3])
                    self._apply_model(view, proj, None)
                    self._edge_gpu.render(GL.GL_LINES)
                    GL.glUniform1f(u["u_opacity"], 1.0)
                    GL.glUniform1i(u["u_mode"], 0)
                    GL.glDisable(GL.GL_POLYGON_OFFSET_FILL)
                    GL.glDepthMask(GL.GL_TRUE)

                # ── 选中板块高亮 pass ──
                if self._hl_gpu is not None and self._hl_gpu.index_count:
                    GL.glEnable(GL.GL_BLEND)
                    GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
                    GL.glDepthMask(GL.GL_FALSE)
                    GL.glEnable(GL.GL_POLYGON_OFFSET_FILL)
                    GL.glPolygonOffset(-2.0, -2.0)
                    GL.glUniform1i(u["u_mode"], 2)
                    GL.glUniform1f(u["u_opacity"], 1.0)
                    self._apply_model(view, proj, None)
                    self._hl_gpu.render(GL.GL_TRIANGLES)
                    GL.glUniform1i(u["u_mode"], 0)
                    GL.glDisable(GL.GL_POLYGON_OFFSET_FILL)
                    GL.glDisable(GL.GL_BLEND)
                    GL.glDepthMask(GL.GL_TRUE)

            # ── 线框叠加 ──
            if self._wireframe:
                GL.glDisable(GL.GL_BLEND)
                GL.glDepthMask(GL.GL_FALSE)
                GL.glUniform1i(u["u_mode"], 1)
                GL.glUniform1f(u["u_opacity"], 1.0)
                for mesh in self._meshes:
                    if mesh.kind not in ("hull", "mount"):
                        continue
                    if mesh.kind == "hull" and (not self._show_hull or self._show_armor):
                        continue
                    if mesh.kind == "mount" and (not self._show_mounts or self._show_armor):
                        continue
                    mesh._build_lines()   # 线框 IBO 只建一次（缓存）
                    for model in _emit_matrices(mesh):
                        self._apply_model(view, proj, model)
                        mesh.render(GL.GL_LINES, line=True)
                self._apply_model(view, proj, None)
                GL.glDepthMask(GL.GL_TRUE)

            # ── Debug：模型点位/名称叠加（mode 2=挂载点位+名称，3=所有模型名称） ──
            if self._debug_mode in (2, 3) and self._meshes:
                self._draw_model_markers(view, proj, self._uniforms, w, h,
                                         mount_only=(self._debug_mode == 2))
        except Exception:  # noqa: BLE001 —— 渲染异常不中断 Qt 绘制循环
            import traceback
            traceback.print_exc()
            pass

        GL.glUseProgram(0)

    def _ensure_scene_fbo(self, w: int, h: int):
        """创建/重建离屏 MRT FBO（未打光 albedo + 世界法线 + 深度）。

        轻量局部 deferred compositing：船体 surface 渲到此 MRT，供 decal_tech
        读取覆盖位置的船体 albedo/世界法线，在光照前合成 decal 法线。
        附件0=albedo(RGBA8 linear)，附件1=世界法线(RGBA8 [0,1] 编码)，深度=DEPTH24。
        """
        if self._scene_fbo and self._scene_fbo_size == (w, h):
            return True   # ★ 已存在且尺寸匹配：必须返回 True，否则 use_surface 变 falsy，
                          #   导致后续帧（如旋转相机）跳过 deferred 路径，走 _draw_ship_solid(非MRT) 报 1282
        if self._scene_fbo:
            GL.glDeleteFramebuffers(1, [self._scene_fbo])
            GL.glDeleteTextures([self._scene_color_tex, self._scene_normal_tex, self._na_tex, self._nb_tex])
            if self._na_fbo:
                GL.glDeleteFramebuffers(1, [self._na_fbo])
            if self._nb_fbo:
                GL.glDeleteFramebuffers(1, [self._nb_fbo])
            GL.glDeleteRenderbuffers(1, [self._scene_depth_rb])
        self._scene_fbo = GL.glGenFramebuffers(1)
        self._scene_color_tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._scene_color_tex)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, w, h, 0,
                        GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, None)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
        self._scene_normal_tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._scene_normal_tex)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, w, h, 0,
                        GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, None)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
        # Normal Ping-Pong FBO：normal_a(存 Hull Normal)、normal_b(存 Final Normal)
        self._na_fbo = GL.glGenFramebuffers(1)
        self._na_tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._na_tex)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, w, h, 0,
                        GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, None)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self._na_fbo)
        GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0,
                                  GL.GL_TEXTURE_2D, self._na_tex, 0)
        glDrawBuffers_na = GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER) == GL.GL_FRAMEBUFFER_COMPLETE
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
        self._nb_fbo = GL.glGenFramebuffers(1)
        self._nb_tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._nb_tex)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, w, h, 0,
                        GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, None)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
        # 深度 RBO 先创建：同时挂到 scene_fbo 与 nb_fbo（共享深度，供 decal pass 遮挡）
        self._scene_depth_rb = GL.glGenRenderbuffers(1)
        GL.glBindRenderbuffer(GL.GL_RENDERBUFFER, self._scene_depth_rb)
        GL.glRenderbufferStorage(GL.GL_RENDERBUFFER, GL.GL_DEPTH_COMPONENT24, w, h)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self._nb_fbo)
        GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0,
                                  GL.GL_TEXTURE_2D, self._nb_tex, 0)
        GL.glFramebufferRenderbuffer(GL.GL_FRAMEBUFFER, GL.GL_DEPTH_ATTACHMENT,
                                     GL.GL_RENDERBUFFER, self._scene_depth_rb)
        ok_nb = GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER) == GL.GL_FRAMEBUFFER_COMPLETE
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self._scene_fbo)
        GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0,
                                  GL.GL_TEXTURE_2D, self._scene_color_tex, 0)
        GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT1,
                                  GL.GL_TEXTURE_2D, self._scene_normal_tex, 0)
        GL.glFramebufferRenderbuffer(GL.GL_FRAMEBUFFER, GL.GL_DEPTH_ATTACHMENT,
                                     GL.GL_RENDERBUFFER, self._scene_depth_rb)
        GL.glDrawBuffers([GL.GL_COLOR_ATTACHMENT0, GL.GL_COLOR_ATTACHMENT1])
        ok = GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER) == GL.GL_FRAMEBUFFER_COMPLETE
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.defaultFramebufferObject())
        # fullscreen quad (覆盖 NDC 的两个三角形，完整 attrib 布局，与网格一致)
        quad = np.array([
            [-1, -1, 0, 0, 0, 1, 0, 0, 1, 1, 1, 1],
            [ 1, -1, 0, 0, 0, 1, 0, 0, 1, 1, 1, 1],
            [-1,  1, 0, 0, 0, 1, 0, 0, 1, 1, 1, 1],
            [ 1, -1, 0, 0, 0, 1, 0, 0, 1, 1, 1, 1],
            [ 1,  1, 0, 0, 0, 1, 0, 0, 1, 1, 1, 1],
            [-1,  1, 0, 0, 0, 1, 0, 0, 1, 1, 1, 1],
        ], dtype=np.float32)
        self._fullscreen_vao = GL.glGenVertexArrays(1)
        self._fullscreen_vbo = GL.glGenBuffers(1)
        GL.glBindVertexArray(self._fullscreen_vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._fullscreen_vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, quad.nbytes, quad, GL.GL_STATIC_DRAW)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, GL.GL_FALSE, _VERTEX_STRIDE, _gl_off(0))
        GL.glEnableVertexAttribArray(1)
        GL.glVertexAttribPointer(1, 3, GL.GL_FLOAT, GL.GL_FALSE, _VERTEX_STRIDE, _gl_off(12))
        GL.glEnableVertexAttribArray(2)
        GL.glVertexAttribPointer(2, 2, GL.GL_FLOAT, GL.GL_FALSE, _VERTEX_STRIDE, _gl_off(24))
        GL.glEnableVertexAttribArray(3)
        GL.glVertexAttribPointer(3, 4, GL.GL_FLOAT, GL.GL_FALSE, _VERTEX_STRIDE, _gl_off(32))
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        GL.glBindVertexArray(0)
        if not (ok and glDrawBuffers_na and ok_nb):
            self._scene_fbo_size = (0, 0)
            return False
        self._scene_fbo_size = (w, h)
        return True

    def _draw_ship_solid(self, view, proj, u, mrt_surface: bool):
        """绘制舰体+挂载（不透明，非透明/贴花/叠加层）。

        供两种目标复用（u_mrt 由调用方设置，本方法不动它）：
        - mrt_surface=True：渲到 scene MRT，shader 输出未打光 albedo + 世界法线。
        - mrt_surface=False：渲到默认 FBO，shader 输出最终光照颜色。
        u_mode 由本方法按材质类型设置（indexed→3，emissive→2，其余→0）。
        """
        GL.glUniform1i(u["u_mode"], 0)
        GL.glUniform1i(u["u_debug_mode"], self._debug_mode)
        GL.glUniform1f(u["u_opacity"], 1.0)
        GL.glUniform1f(u["u_emissive"], 0.0)
        GL.glUniform1f(u["u_emissive_k"], 1.0)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glUniform1i(u["u_tex"], 0)
        self._apply_model(view, proj, None)
        for mesh in self._meshes:
            if mesh.kind not in ("hull", "mount"):
                continue
            if _is_alpha_blend(mesh):
                continue  # 线网/半透明/alpha 贴花走透明 pass
            if getattr(mesh, "is_overlay", False):
                continue  # 法线叠加层在 Pass3 单独渲
            if mesh.kind == "hull" and (not self._show_hull or self._show_armor):
                continue
            if mesh.kind == "mount" and (not self._show_mounts or self._show_armor):
                continue
            # ★ 材质只绑定一次，实例循环只更新模型矩阵（省每帧上千次重复绑定）
            self._bind_solid_material(u, mesh)
            self._emit_instances(view, proj, mesh, u=u)
        self._apply_model(view, proj, None, u)
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)

    def _bind_solid_material(self, u, mesh):
        """绑定网格材质（uniform + 贴图 + INDEXED 分块参数）——**每个网格只做一次**。

        与逐实例 draw 分离：实例循环里只更新 u_mvp/u_normal_mat 再 render，
        避免为 N 个实例重复绑定贴图/uniform（旋转相机时每帧上千次调用的卡顿源）。
        """
        if mesh.tech_family == "indexed":
            # INDEXED（2.0 分块涂装）：舰体 hull 与炮塔/装饰 mount 均走分块渲染
            self._bind_indexed(mesh, u)
            return
        # emissive 自发光：无光照 + diffuse blue 自发光增益（强度 = emissivePower）
        GL.glUniform1i(u["u_mode"], 2 if mesh.tech_family == "emissive" else 0)
        GL.glUniform1f(u["u_emissive"], 1.0 if mesh.tech_family == "emissive" else 0.0)
        GL.glUniform1f(u["u_emissive_k"], float(mesh.emissive_power or 1.0))
        if mesh.has_tex:
            GL.glBindTexture(mesh._texture_target, mesh._texture)
            GL.glUniform1i(u["u_has_tex"], 1)
        else:
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
            GL.glUniform1i(u["u_has_tex"], 0)
        # 法线贴图（标准 PBS）：材质声明 normalMap/g_normalMap 则绑定到单元 6，
        # 用其扰动光照法线；未声明则用几何法线。
        _nm = 0
        if mesh._extra_tex:
            for _k in ("normalMap", "g_normalMap"):
                if _k in mesh._extra_tex:
                    _nm = mesh._extra_tex[_k]
                    break
        if _nm:
            GL.glActiveTexture(GL.GL_TEXTURE6)
            GL.glBindTexture(GL.GL_TEXTURE_2D, _nm)
            GL.glUniform1i(u["u_normal_map"], 6)
            GL.glUniform1i(u["u_has_normal_map"], 1)
        else:
            GL.glUniform1i(u["u_has_normal_map"], 0)
        # ★ 关键：法线贴图绑到单元 6 后，必须把活动纹理单元切回 0，
        #   否则下一个网格的 diffuse 会绑到单元 6，而 u_tex 仍采样单元 0 → 串贴图。
        GL.glActiveTexture(GL.GL_TEXTURE0)

    def _emit_instances(self, view, proj, mesh, line=False, u=None):
        """逐实例绘制：只更新模型矩阵，不重复绑定材质/贴图（每网格只 bind 一次）。"""
        for model in _emit_matrices(mesh):
            self._apply_model(view, proj, model, u)
            mesh.render(GL.GL_TRIANGLES if not line else GL.GL_LINES, line=line)

    @staticmethod
    def _bind_alpha_material(u, mesh):
        """透明/贴花单次材质绑定（uniform + 贴图）——每个网格只做一次。"""
        if mesh.has_tex:
            GL.glBindTexture(mesh._texture_target, mesh._texture)
            GL.glUniform1i(u["u_has_tex"], 1)
        else:
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
            GL.glUniform1i(u["u_has_tex"], 0)

    def _draw_alpha_once(self, view, proj, u, mesh, model):
        """透明 pass 单次绘制一个网格（应用模型矩阵 + 绑定贴图）。"""
        GL.glUseProgram(self._program)
        self._apply_model(view, proj, model, u)
        self._bind_alpha_material(u, mesh)
        mesh.render(GL.GL_TRIANGLES)

    def _draw_decal_once(self, view, proj, u, mesh, model):
        """贴花（dec_tech/amgn）单次绘制一个网格（应用模型矩阵 + 绑定贴图）。"""
        GL.glUseProgram(self._program)
        self._apply_model(view, proj, model, u)
        self._bind_alpha_material(u, mesh)
        # 诊断：清空历史错误，渲染后捕获当前 GL error（定位 1282）
        while GL.glGetError() != GL.GL_NO_ERROR:
            pass
        mesh.render(GL.GL_TRIANGLES)
        err = GL.glGetError()
        if err != GL.GL_NO_ERROR:
            print(f"[GL] decal draw err=0x{err:x} mesh={mesh.name!r} "
                  f"verts={mesh._vdata.shape[0] if hasattr(mesh,'_vdata') else -1} "
                  f"idx={mesh.index_count} vao={int(mesh._vao)} ibo={int(mesh._ibo)} "
                  f"vbo_bytes={mesh._vdata.nbytes if hasattr(mesh,'_vdata') else -1}")

    def _draw_model_markers(self, view, proj, u, w, h, mount_only: bool):
        """debug(2/3)：显示模型点位 + 名称（挂载为黄点，船体等为青点）。

        mount_only=True：只显示挂载模型点位（mode 2）；
        mount_only=False：显示所有渲染模型(Hull/Mount)中心点与名称（mode 3）。
        名称投影到屏幕记录到 self._mount_labels，由 paintEvent 叠加文本。
        """
        def _label_for(m):
            """模式 3 显示各模型自身形状名/骨骼节点名（替代几何文件名）。"""
            if getattr(self, '_debug_mode', 0) == 3:
                sn = getattr(m, 'shape_names', None) or []
                nn = getattr(m, 'node_names', None) or []
                if sn:
                    return ", ".join(str(s) for s in sn[:3]) + (
                        "…" if len(sn) > 3 else "")
                if nn:
                    return ", ".join(str(n) for n in nn[:3]) + (
                        "…" if len(nn) > 3 else "")
            return getattr(m, 'name', "")

        pts = []
        cols = []
        names = []
        for m in self._meshes:
            if m.kind not in ("hull", "mount"):
                continue
            if mount_only and m.kind != "mount":
                continue
            if m.kind == "hull" and (not self._show_hull or self._show_armor):
                continue
            if m.kind == "mount" and (not self._show_mounts or self._show_armor):
                continue
            # 网格代表点（质心）：挂载用 model_matrix 平移；船体用顶点质心
            v = getattr(m, "_vdata", None)
            if v is not None and v.shape[0]:
                c = v[:, 0:3].mean(axis=0)
                cx, cy, cz = float(c[0]), float(c[1]), float(c[2])
            else:
                cx, cy, cz = 0.0, 0.0, 0.0
            mm = m.model_matrix
            insts = getattr(m, "instance_matrices", None) or []
            if insts:
                # 多节点实例化：每实例一个点位（质心经实例矩阵变换）
                base = mm
                for inst in insts:
                    wm = (inst if base is None else base @ inst)
                    p = np.asarray([cx, cy, cz, 1.0], dtype=np.float64)
                    wp = wm @ p
                    x, y, z = float(wp[0]), float(wp[1]), float(wp[2])
                    pts.append((x, y, z))
                    cols.append((1.0, 0.9, 0.2, 1.0) if m.kind == "mount" else (0.3, 0.8, 1.0, 1.0))
                    names.append((x, y, z, _label_for(m)))
            else:
                if mm is not None:
                    x = float(mm[0, 3]); y = float(mm[1, 3]); z = float(mm[2, 3])
                else:
                    x, y, z = cx, cy, cz
                pts.append((x, y, z))
                cols.append((1.0, 0.9, 0.2, 1.0) if m.kind == "mount" else (0.3, 0.8, 1.0, 1.0))
                names.append((x, y, z, _label_for(m)))
        # 投影到屏幕，供 paintEvent 画名称
        self._mount_labels = []
        if not pts:
            return
        try:
            for (x, y, z, name) in names:
                clip = proj @ view @ np.array([x, y, z, 1.0], dtype=np.float64)
                wc = float(clip[3])
                if wc <= 1e-6:      # 点在相机后方/透视除法无效，跳过避免坐标爆炸
                    continue
                ndc = clip[:3] / wc
                sx = (float(ndc[0]) * 0.5 + 0.5) * w
                sy = (1.0 - (float(ndc[1]) * 0.5 + 0.5)) * h
                # 只保留屏幕邻近点，防止投影到相机后方时坐标溢出
                if not (-w < sx < w * 2 and -h < sy < h * 2):
                    continue
                self._mount_labels.append((sx, sy, name))
        except Exception:
            self._mount_labels = []
        pos = np.asarray(pts, dtype=np.float32).reshape(-1, 3)
        col = np.asarray(cols, dtype=np.float32).reshape(-1, 4)
        n = pos.shape[0]
        vbo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, pos.nbytes, pos, GL.GL_STATIC_DRAW)
        cbo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, cbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, col.nbytes, col, GL.GL_STATIC_DRAW)
        vao = GL.glGenVertexArrays(1)
        GL.glBindVertexArray(vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, GL.GL_FALSE, 12, _gl_off(0))
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, cbo)
        GL.glEnableVertexAttribArray(3)
        GL.glVertexAttribPointer(3, 4, GL.GL_FLOAT, GL.GL_FALSE, 16, _gl_off(0))
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        GL.glBindVertexArray(0)
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glDisable(GL.GL_BLEND)
        GL.glUniform1i(u["u_mode"], 1)      # 无光照直显颜色
        GL.glUniform1i(u["u_has_tex"], 0)
        GL.glUniform1f(u["u_opacity"], 1.0)
        self._apply_model(view, proj, None)
        GL.glPointSize(6.0)
        GL.glBindVertexArray(vao)
        GL.glDrawArrays(GL.GL_POINTS, 0, n)
        GL.glBindVertexArray(0)
        GL.glPointSize(1.0)
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glDeleteVertexArrays(1, [vao])
        GL.glDeleteBuffers(2, [vbo, cbo])

    def _bind_indexed(self, mesh, u):
        """绑定 INDEXED 分块贴图与参数（u_mode=3），供 paintGL 调用。

        纹理单元：0=materialIdMap 1=albedoArray(tiles) 2=artMap。
        分块参数来自材质 .mfm 的 vec4 数组（真实 6 数组，见 check_aquitaine）：
          tileIdxMatIdArr     → u_tile_idx[196]：每材质ID (albedo瓦片, normal, MG, disableMGNCamo)
          albedoTintMatIdArr  → u_tint[196]：每材质ID 调色(RGB) + 强度(w)
          offsetScaleMatIdArr → u_grid=(zw 38,38), u_grid_offset=(xy 0,0)
          artStrengthMatIdArr → art 叠加强度（取第一元素）
        """
        ex = mesh._extra_tex
        ip = mesh.indexed_params or {}
        arrays = ip.get("arrays") or {}
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, ex.get("materialIdMap", 0))
        GL.glUniform1i(u["u_matid_tex"], 0)
        GL.glActiveTexture(GL.GL_TEXTURE1)
        GL.glBindTexture(GL.GL_TEXTURE_2D_ARRAY, ex.get("albedoArray", 0))
        GL.glUniform1i(u["u_tiles_tex"], 1)
        GL.glActiveTexture(GL.GL_TEXTURE2)
        GL.glBindTexture(GL.GL_TEXTURE_2D_ARRAY, ex.get("normalArray", 0))
        GL.glUniform1i(u["u_normal_tex"], 2)
        GL.glActiveTexture(GL.GL_TEXTURE5)
        GL.glBindTexture(GL.GL_TEXTURE_2D, ex.get("normalMap", 0))
        GL.glUniform1i(u["u_alpha_n_map"], 5)
        GL.glActiveTexture(GL.GL_TEXTURE3)
        GL.glBindTexture(GL.GL_TEXTURE_2D, ex.get("artMap", 0))
        GL.glUniform1i(u["u_art_tex"], 3)
        GL.glActiveTexture(GL.GL_TEXTURE4)
        GL.glBindTexture(GL.GL_TEXTURE_2D_ARRAY, ex.get("rgbNoiseMap", 0))
        GL.glUniform1i(u["u_noise_tex"], 4)

        def _arr(name):
            a = arrays.get(name)
            if a is not None and getattr(a, "size", 0) >= 196 * 4:
                return np.ascontiguousarray(a[:196], dtype=np.float32).reshape(-1)
            return np.zeros(196 * 4, dtype=np.float32)

        # INDEXED 官方 5 数组（196×4）→ uniform 数组
        # 省寄存器：u_rotation 一个 vec4[196] 同时装 rotation(.x) + artStrength BaseStrength(.y)
        rotart = np.zeros((196, 4), dtype=np.float32)
        rd = arrays.get("rotationMatIdArr")
        if rd is not None and getattr(rd, "size", 0) >= 196 * 4:
            rotart[:, 0] = np.asarray(rd, dtype=np.float32).reshape(-1, 4)[:196, 0]
        ad = arrays.get("artStrengthMatIdArr")
        if ad is not None and getattr(ad, "size", 0) >= 196 * 4:
            rotart[:, 1] = np.asarray(ad, dtype=np.float32).reshape(-1, 4)[:196, 0]
        GL.glUniform4fv(u["u_rotation"], 196, np.ascontiguousarray(rotart.reshape(-1)))
        # ★ Reciprocal 优化：offsetScaleMatIdArr.zw 是 CPU 端**原始尺寸**（38/25/…），
        #   上传到 shader 前预取倒数 1/raw，使乘法 uv = v_uv*sc 在倒数空间下等价于 uv/raw，
        #   避免大幅值 UV（~[-91,76]）被放大几千倍→平铺→白色条带。退化(0)保持 0，shader 回退。
        _os = _arr("offsetScaleMatIdArr")
        if _os.size >= 196 * 4:
            _osm = np.ascontiguousarray(_os.reshape(196, 4)).copy()
            _sx = _osm[:, 2].copy(); _sy = _osm[:, 3].copy()
            _osm[:, 2] = np.where(_sx > 0.0, 1.0 / np.maximum(_sx, 1e-6), 0.0)
            _osm[:, 3] = np.where(_sy > 0.0, 1.0 / np.maximum(_sy, 1e-6), 0.0)
            GL.glUniform4fv(u["u_offset_scale"], 196, np.ascontiguousarray(_osm.reshape(-1)))
        else:
            GL.glUniform4fv(u["u_offset_scale"], 196, np.zeros(196 * 4, dtype=np.float32))
        GL.glUniform4fv(u["u_tile_idx"], 196, _arr("tileIdxMatIdArr"))
        GL.glUniform4fv(u["u_tint"], 196, _arr("albedoTintMatIdArr"))
        GL.glUniform4fv(u["u_remove"], 196, _arr("albedoToRemoveTintMatIdArr"))
        # tint 混合 gamma（官方 g_gammaCorrection≈2.2：把 sRGB albedo/tint 转线性，再输出转回 sRGB）
        GL.glUniform1f(u["u_gamma"], 2.2)
        GL.glUniform1i(u["u_has_tex"], 0)
        GL.glUniform1i(u["u_has_normal_map"], 0)   # indexed 不走标准法线贴图（用 normalArray）
        GL.glUniform1i(u["u_mode"], 3)
        GL.glActiveTexture(GL.GL_TEXTURE0)

    def _draw_fullscreen(self, mode, w, h):
        """用独立 fullscreen program（gl_VertexID 生成 NDC 三角形，无 VAO/attrib）渲全屏。"""
        GL.glUseProgram(self._fs_program)
        fu = self._fs_uniforms
        GL.glUniform1i(fu["u_mode"], mode)
        GL.glUniform2f(fu["u_viewport"], float(w), float(h))
        GL.glUniform3f(fu["u_light_dir"], 0.35, 0.6, 0.72)
        GL.glUniform3f(fu["u_ambient"], 0.12, 0.12, 0.14)
        GL.glUniform1i(fu["u_scene_tex"], 5)
        GL.glUniform1i(fu["u_scene_normal_tex"], 1)
        GL.glUniform1i(fu["u_scene_final_tex"], 8)
        # core profile 下 glDrawArrays 需要绑定 VAO（即使顶点由 gl_VertexID 生成）
        GL.glBindVertexArray(self._fullscreen_vao)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, 6)
        GL.glBindVertexArray(0)
        GL.glUseProgram(self._program)

    def _apply_model(self, view: np.ndarray, proj: np.ndarray,
                     model: np.ndarray | None, u=None):
        """按网格模型矩阵设置 u_mvp / u_normal_mat（None = 恒等）。

        model 为行主序 4x4（渲染空间）；挂载网格需矩阵定位，舰体/装甲恒等。
        u：uniform 表；None = 单输出 program（_uniforms）。MRT 传 _uniforms_mrt。
        """
        if u is None:
            u = self._uniforms
        if model is None:
            m = np.eye(4, dtype=np.float32)
        else:
            m = model
        mvp = np.ascontiguousarray((proj @ view @ m).T, dtype=np.float32)
        nm = np.ascontiguousarray(m[:3, :3].T, dtype=np.float32)
        GL.glUniformMatrix4fv(u["u_mvp"], 1, GL.GL_FALSE, mvp)
        GL.glUniformMatrix3fv(u["u_normal_mat"], 1, GL.GL_FALSE, nm)

    # ── 交互 ─────────────────────────────────────────────

    def paintEvent(self, event):
        super().paintEvent(event)
        # debug(2/3)：叠加模型点位名称
        if self._debug_mode in (2, 3) and self._mount_labels:
            painter = QPainter(self)
            painter.setPen(QColor(255, 230, 0))
            f = painter.font()
            f.setPointSize(8)
            painter.setFont(f)
            for sx, sy, name in self._mount_labels:
                painter.drawText(int(sx) + 4, int(sy) - 4, name)
            painter.end()

    def keyPressEvent(self, event):
        """Debug 切换：N 循环 0(关)/1(最终法线)/2(挂载点位+名称)/3(所有模型名称)。"""
        k = event.key()
        if k == Qt.Key_N:
            self._debug_mode = (self._debug_mode + 1) % 4
            self.update()
            return
        mapping = {Qt.Key_0: 0, Qt.Key_Escape: 0, Qt.Key_1: 1, Qt.Key_2: 2, Qt.Key_3: 3}
        if k in mapping:
            self._debug_mode = mapping[k]
            self.update()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        self._last_pos = event.position().toPoint()
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint()

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.position().toPoint()
        buttons = event.buttons()
        if not buttons:
            # 悬停拾取（节流 ~30fps）
            self._hover_pick(pos)
            self._last_pos = pos
            return
        if self._last_pos is None:
            self._last_pos = pos
            return
        dx = pos.x() - self._last_pos.x()
        dy = pos.y() - self._last_pos.y()
        self._last_pos = pos
        if buttons & Qt.LeftButton:
            self._camera.rotate(-dx * 0.4, dy * 0.4)
            self.update()
        elif buttons & Qt.RightButton:
            self._camera.pan(dx, dy, max(self.height(), 1))
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self._press_pos is not None:
            pos = event.position().toPoint()
            moved = (pos - self._press_pos).manhattanLength()
            self._press_pos = None
            if moved < 5 and self._armor_scene is not None and self._show_armor:
                # 点击选中/取消选中板块
                hit = self.pick_at(pos.x(), pos.y())
                key = hit[1].plate_key if hit else None
                if key == self._selected_plate:
                    key = None
                self.select_plate(key)
                if self.on_select is not None:
                    self.on_select(key)
        self._last_pos = None

    def _hover_pick(self, pos):
        """鼠标悬停拾取：更新 hover 三角形并回调 on_hover。"""
        if self._armor_scene is None or self.on_hover is None:
            return
        if not self._show_armor:
            # 装甲未显示时不做拾取：清除悬停状态并隐藏提示
            if self._hover_tri is not None:
                self._hover_tri = None
                self.on_hover(None, QPoint())
            return
        now = time.perf_counter()
        if now - self._last_pick_time < 0.033:
            return
        self._last_pick_time = now
        hit = self.pick_at(pos.x(), pos.y())
        tri = hit[0] if hit else None
        if tri != self._hover_tri:
            self._hover_tri = tri
        global_pos = self.mapToGlobal(pos)
        self.on_hover(tri, global_pos)

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        factor = (0.88 if delta > 0 else 1.0 / 0.88)
        self._camera.zoom(factor)
        self.update()

    def leaveEvent(self, event):
        self._last_pos = None
        if self._hover_tri is not None:
            self._hover_tri = None
            if self.on_hover is not None:
                self.on_hover(None, QPoint())
