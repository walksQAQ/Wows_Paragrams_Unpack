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
from OpenGL.error import GLError

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
layout(location = 8) in vec4 i_model0;
layout(location = 9) in vec4 i_model1;
layout(location = 10) in vec4 i_model2;
layout(location = 11) in vec4 i_model3;
uniform mat4 u_mvp;
uniform mat3 u_normal_mat;
out vec4 v_color;
out vec3 v_normal;
out vec2 v_uv;
out vec3 v_world_pos;
void main() {
    mat4 model = mat4(i_model0, i_model1, i_model2, i_model3);
    vec4 wp = model * vec4(in_position, 1.0);
    gl_Position = u_mvp * wp;
    v_normal = u_normal_mat * mat3(model) * in_normal;
    v_color = in_color;
    v_uv = in_uv;
    v_world_pos = wp.xyz;
}
"""

TEX_VERT_SRC = """
#version 400 core
out vec4 v_color;
out vec3 v_normal;
out vec2 v_uv;
out vec3 v_world_pos;
void main() {
    vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
    v_color = vec4(1.0);
    v_normal = vec3(0.0, 0.0, 1.0);
    v_uv = vec2(0.0);
    v_world_pos = vec3(0.0);
}
"""

#: ★ PBS / 实体 shader（u_mode 0/1/2）：标准材质 + emissive + 线框。只声明 PBS 用到的 sampler，
#:   与 INDEXED/FX 的纹理单元完全独立（2026-08-27 渲染逻辑拆分第二次）。
FRAG_PBS = """
#version 400 core
in vec4 v_color;
 in vec3 v_normal;
 in vec2 v_uv;
uniform int u_mode;        // 0=光照实体 1=线框 2=无光照实体(emissive/透明)
uniform float u_opacity;
uniform vec3 u_light_dir;
uniform vec3 u_ambient;
uniform sampler2D u_tex;
uniform int u_has_tex;
uniform float u_emissive;
uniform float u_emissive_k;
uniform sampler2D u_normal_map;
uniform int u_has_normal_map;
uniform sampler2D u_mg_map;
uniform int u_has_mg;
uniform vec3 u_view_dir;              // 观察方向（反射用）
uniform int u_mrt;
uniform int u_debug_mode;             // 5=涂装覆盖强度 Debug（PBS 显示 _mg.B；INDEXED 显示 art 覆盖）
uniform vec3 u_light_pos;             // 点光源位置（天上）
uniform float u_normal_strength;      // 法线贴图强度（>1 加强凹凸细节）
in vec3 v_world_pos;                  // 世界坐标（点光源用）
out vec4 fragColor;
out vec4 fragNormal;                   // MRT 附件1 输出（世界法线，[0,1] 编码）
out vec3 fragWorldPos;                // MRT 附件2：世界坐标（供最终点光源）
// 统一 PBR：Cook-Torrance GGX + Schlick Fresnel 直接光镜面反射（天上的点光源）。
// ★ 已移除程序化天空盒环境反射：金属只反射光源高光，不反射天空/海面色相。
vec3 pbr_light(vec3 albedo, vec3 N, float metallic, float gloss, vec3 lit, vec3 worldPos) {
    vec3 path = u_light_pos - worldPos;
    float dist = max(length(path), 1e-4);
    vec3 L = path / dist;
    float atten = clamp(1.0 / (1.0 + 0.0008 * dist * dist), 0.0, 1.0);
    vec3 V = normalize(u_view_dir);
    vec3 H = normalize(L + V);
    float NdotL = max(dot(N, L), 0.0);
    float NdotV = max(dot(N, V), 0.0);
    float NdotH = max(dot(N, H), 0.0);
    float VdotH = max(dot(V, H), 0.0);
    float roughness = clamp(1.0 - gloss, 0.04, 1.0);
    vec3 F0 = mix(vec3(0.04), albedo, metallic);
    vec3 F = F0 + (1.0 - F0) * pow(1.0 - VdotH, 5.0);
    float a = roughness * roughness; float a2 = a * a;
    float denom = NdotH * NdotH * (a2 - 1.0) + 1.0;
    float D = a2 / max(3.14159265 * denom * denom, 1e-5);
    float k = (roughness + 1.0); k = k * k / 8.0;
    float Gv = NdotV / (NdotV * (1.0 - k) + k);
    float Gl = NdotL / (NdotL * (1.0 - k) + k);
    float G = Gv * Gl;
    vec3 specular = (D * G * F) / max(4.0 * NdotV * NdotL, 1e-5);
    // MG 不影响基础颜色：diffuse 恒定 = albedo*lit（背光面靠 half-Lambert/ambient 保底）。
    // 点光源：漫反射与高光都随距离衰减；metallic 经 F0 控反射，gloss 控高光宽度。
    vec3 diffuse = albedo * lit;
    // 环境光不随点光源距离衰减（保底照亮，照不到的地方不黑）；点光源方向/高光部分随距离衰减。
    vec3 ambient_part = albedo * u_ambient;
    vec3 direct = ambient_part + (diffuse - ambient_part) * atten + specular * NdotL * atten * 2.0;
    return direct;
}
void main() {
    vec4 base = v_color;
    bool is_tex = (u_has_tex == 1);
    if (is_tex) {
        base = texture(u_tex, v_uv);
    }
    if (u_mode == 1) {
        // 线框/平涂：直接显色
        fragColor = vec4(base.rgb, 1.0);
        return;
    }
    vec3 N = normalize(v_normal);
    // 标准 PBS 法线贴图：材质声明了 normalMap 则只遵循法线贴图
    if (u_has_normal_map == 1) {
        vec3 nm = texture(u_normal_map, v_uv).rgb;
        vec3 n_ts = vec3(nm.x * 2.0 - 1.0, nm.y * 2.0 - 1.0, 0.0);
        n_ts.xy *= u_normal_strength;   // ★ 加强法线，突出 _n 凹凸细节
        n_ts.z = sqrt(max(1.0 - (n_ts.x*n_ts.x + n_ts.y*n_ts.y), 0.0));
        N = normalize(n_ts);
    }
    // _mg（metallicGlossMap）：R=metallic, G=gloss, B=发光/涂装强度
    float metallic = 0.0; float gloss = 0.0; float emit = 0.0;
    if (u_has_mg == 1) {
        vec3 mg = texture(u_mg_map, v_uv).rgb;
        metallic = mg.r; gloss = mg.g; emit = mg.b;
    }
    if (u_mrt == 1) {
        // 轻量 deferred surface：标准 PBS/emissive 存未打光 albedo + 世界法线；
        // a 携带 metallic、fragNormal.a 携带 gloss；fragWorldPos 供最终点光源重建位置。
        fragColor = vec4(base.rgb, metallic);
        fragNormal = vec4(N * 0.5 + 0.5, gloss);
        fragWorldPos = v_world_pos;
        return;
    }
    vec3 n = N;
    vec3 litL = normalize(u_light_pos - v_world_pos);   // 点光源方向
    float diff = max(dot(n, litL), 0.0);
    float hl = diff * 0.5 + 0.5;   // half-Lambert：远侧永不黑
    vec3 lit = u_ambient + (1.0 - u_ambient) * hl;
    vec3 rgb2;
    if (u_mode == 2) {
        rgb2 = base.rgb;
        if (u_emissive > 0.5) {
            // ★ 自发光：颜色 × mask(_mg.B，无 _mg 退回 diffuse.blue) × emissive_power。
            //   独立加到基础颜色，不受 NdotL/metallic/gloss/阴影影响。
            float em = (u_has_mg == 1) ? emit : base.b;
            vec3 emissive = base.rgb * em * u_emissive_k;
            rgb2 = base.rgb + emissive;
        }
    } else {
        rgb2 = pbr_light(base.rgb, n, metallic, gloss, lit, v_world_pos);
        if (u_emissive > 0.5) {
            // 自发光加到最终 PBR 结果之后（独立项，不参与 diffuse/specular）。
            float em = (u_has_mg == 1) ? emit : base.b;
            rgb2 += base.rgb * em * u_emissive_k;
        }
    }
    if (u_debug_mode == 5) {
        // 涂装覆盖强度 debug：显示 _mg.B（camo/mg 蓝通道）灰度，无 _mg 则 0。
        rgb2 = vec3(emit);
    }
    if (is_tex) {
        rgb2 = pow(rgb2, vec3(1.0 / 2.2));
    }
    fragColor = vec4(rgb2, base.a * u_opacity);
}
"""

#: PBS 单输出变体（移除 fragNormal 声明与 MRT 赋值），用于单 drawbuffer 目标。
FRAG_PBS_SINGLE = FRAG_PBS.replace(
    "out vec4 fragColor;\nout vec4 fragNormal;                   // MRT 附件1 输出（世界法线，[0,1] 编码）\nout vec3 fragWorldPos;                // MRT 附件2：世界坐标（供最终点光源）",
    "out vec4 fragColor;",
).replace(
    "        fragNormal = vec4(N * 0.5 + 0.5, gloss);\n        fragWorldPos = v_world_pos;\n        return;",
    "        return;",
)

#: ★ FX / decal / fullscreen shader（u_mode 4/5/7/9/10/11/12）：decal 法线合成 + 最终光照。
#:   只声明 FX 用到的 sampler（u_tex 供 decal / u_scene_* 供合成），与 INDEXED/PBS 独立。
FRAG_FX = """
#version 400 core
in vec4 v_color;
 in vec3 v_normal;
 in vec2 v_uv;
uniform int u_mode;
uniform float u_opacity;
uniform vec3 u_light_dir;
uniform vec3 u_ambient;
uniform sampler2D u_tex;
uniform int u_has_tex;
uniform sampler2D u_scene_tex;         // MRT 附件0：船体未打光 albedo（linear）
uniform sampler2D u_scene_normal_tex;  // MRT 附件1：船体世界法线
uniform sampler2D u_scene_final_tex;   // MRT 附件2：Final Normal（Hull+decal 合成）
uniform vec2 u_viewport;               // 视口尺寸（换算屏幕 UV）
uniform vec3 u_view_dir;              // 观察方向（反射用）
uniform vec3 u_light_pos;             // 点光源位置（天上）
uniform float u_normal_strength;      // 法线强度（加强 _n）
uniform sampler2D u_scene_world_tex;  // MRT 附件2：世界坐标（点光源重建位置）
out vec4 fragColor;
// 统一 PBR：Cook-Torrance GGX + Schlick Fresnel 直接光镜面反射（天上的点光源）。
// ★ 已移除程序化天空盒环境反射：金属只反射光源高光，不反射天空/海面色相。
vec3 pbr_light(vec3 albedo, vec3 N, float metallic, float gloss, vec3 lit, vec3 worldPos) {
    vec3 path = u_light_pos - worldPos;
    float dist = max(length(path), 1e-4);
    vec3 L = path / dist;
    float atten = clamp(1.0 / (1.0 + 0.0008 * dist * dist), 0.0, 1.0);
    vec3 V = normalize(u_view_dir);
    vec3 H = normalize(L + V);
    float NdotL = max(dot(N, L), 0.0);
    float NdotV = max(dot(N, V), 0.0);
    float NdotH = max(dot(N, H), 0.0);
    float VdotH = max(dot(V, H), 0.0);
    float roughness = clamp(1.0 - gloss, 0.04, 1.0);
    vec3 F0 = mix(vec3(0.04), albedo, metallic);
    vec3 F = F0 + (1.0 - F0) * pow(1.0 - VdotH, 5.0);
    float a = roughness * roughness; float a2 = a * a;
    float denom = NdotH * NdotH * (a2 - 1.0) + 1.0;
    float D = a2 / max(3.14159265 * denom * denom, 1e-5);
    float k = (roughness + 1.0); k = k * k / 8.0;
    float Gv = NdotV / (NdotV * (1.0 - k) + k);
    float Gl = NdotL / (NdotL * (1.0 - k) + k);
    float G = Gv * Gl;
    vec3 specular = (D * G * F) / max(4.0 * NdotV * NdotL, 1e-5);
    // MG 不影响基础颜色。环境光保底不衰减，点光源贡献随距离衰减。
    vec3 diffuse = albedo * lit;
    vec3 ambient_part = albedo * u_ambient;
    vec3 direct = ambient_part + (diffuse - ambient_part) * atten + specular * NdotL * atten * 2.0;
    return direct;
}
void main() {
    vec4 base = v_color;
    bool is_tex = (u_has_tex == 1);
    if (is_tex) {
        base = texture(u_tex, v_uv);
    }
    if (u_mode == 4) {
        vec2 suv = gl_FragCoord.xy / u_viewport;
        suv.y = 1.0 - suv.y;
        vec3 base_albedo = texture(u_scene_tex, suv).rgb;
        vec3 baseN = normalize(texture(u_scene_normal_tex, suv).rgb * 2.0 - 1.0);
        vec4 nmap = (u_has_tex == 1) ? texture(u_tex, v_uv) : vec4(0.5, 0.5, 1.0, 0.0);
        vec3 n_ts = vec3(nmap.x * 2.0 - 1.0, nmap.y * 2.0 - 1.0, 0.0);
        n_ts.z = sqrt(max(1.0 - (n_ts.x*n_ts.x + n_ts.y*n_ts.y), 0.0));
        n_ts = normalize(n_ts);
        vec3 decal_n = normalize(n_ts);
        vec3 merged = normalize(baseN + (decal_n - vec3(0.0, 0.0, 1.0)));
        float diff = max(dot(merged, -u_light_dir), 0.0);
        float hl = diff * 0.5 + 0.5;
        vec3 lit = u_ambient + (1.0 - u_ambient) * hl;
        vec3 col = base_albedo * lit;
        col = pow(col, vec3(1.0 / 2.2));
        float mask = 1.0 * u_opacity;
        fragColor = vec4(col, mask);
        return;
    }
    if (u_mode == 5) {
        vec4 nmap5 = (u_has_tex == 1) ? texture(u_tex, v_uv) : vec4(0.5, 0.5, 1.0, 0.0);
        vec3 n5 = vec3(nmap5.x * 2.0 - 1.0, nmap5.y * 2.0 - 1.0, 0.0);
        n5.z = sqrt(max(1.0 - (n5.x*n5.x + n5.y*n5.y), 0.0));
        n5 = normalize(n5);
        vec3 dn = normalize(n5);
        fragColor = vec4(normalize(dn) * 0.5 + 0.5, 1.0);
        return;
    }
    if (u_mode == 9) {
        vec2 suv = gl_FragCoord.xy / u_viewport;
        // 读原 Hull Normal(na_tex)：rgb=法线，.a=gloss(Pass1 存的)，合成时保留 gloss
        vec4 hn = texture(u_scene_normal_tex, suv);
        vec3 hullN = normalize(hn.rgb * 2.0 - 1.0);
        float keep_gloss = hn.a;
        vec4 nmap = (u_has_tex == 1) ? texture(u_tex, v_uv) : vec4(0.5, 0.5, 1.0, 1.0);
        vec3 n_ts = vec3(nmap.x * 2.0 - 1.0, nmap.y * 2.0 - 1.0, 0.0);
        n_ts.z = sqrt(max(1.0 - (n_ts.x*n_ts.x + n_ts.y*n_ts.y), 0.0));
        n_ts = normalize(n_ts);
        vec3 decal_n = normalize(n_ts);
        vec3 merged = normalize(hullN + (decal_n - vec3(0.0, 0.0, 1.0)));
        fragColor = vec4(merged * 0.5 + 0.5, keep_gloss);
        return;
    }
    if (u_mode == 10) {
        vec2 suv = gl_FragCoord.xy / u_viewport;
        fragColor = texture(u_scene_normal_tex, suv);
        return;
    }
    if (u_mode == 11) {
        // 最终 Lighting：读 Hull Albedo + Final Normal + 世界坐标，用点光源 PBR 打光。
        vec2 suv = gl_FragCoord.xy / u_viewport;
        vec4 scenec = texture(u_scene_tex, suv);
        vec3 albedo = scenec.rgb;
        float metallic = scenec.a;
        vec4 scenen = texture(u_scene_final_tex, suv);
        vec3 N = normalize(scenen.rgb * 2.0 - 1.0);
        float gloss = scenen.a;
        vec3 worldPos = texture(u_scene_world_tex, suv).xyz;
        vec3 litL = normalize(u_light_pos - worldPos);
        float diff = max(dot(N, litL), 0.0);
        float hl = diff * 0.5 + 0.5;
        vec3 lit = u_ambient + (1.0 - u_ambient) * hl;
        vec3 col = pbr_light(albedo, N, metallic, gloss, lit, worldPos);
        col = pow(col, vec3(1.0 / 2.2));
        fragColor = vec4(col, 1.0);
        return;
    }
    if (u_mode == 12) {
        // Debug 法线：直接显色「最终法线」（normal_b = Hull+Decal 合成）。
        vec2 suv = gl_FragCoord.xy / u_viewport;
        fragColor = texture(u_scene_final_tex, suv);
        return;
    }
    if (u_mode == 13) {
        // Debug metallic：显色 scene_color_tex.a（Pass1 存的 metallic）。
        vec2 suv = gl_FragCoord.xy / u_viewport;
        float m = texture(u_scene_tex, suv).a;
        fragColor = vec4(vec3(m), 1.0);
        return;
    }
    if (u_mode == 14) {
        // Debug gloss：显色 nb_tex.a（Pass1 存的 gloss）。
        vec2 suv = gl_FragCoord.xy / u_viewport;
        float g = texture(u_scene_final_tex, suv).a;
        fragColor = vec4(vec3(g), 1.0);
        return;
    }
    if (u_mode == 7) {
        vec2 suv = gl_FragCoord.xy / u_viewport;
        vec3 base_albedo = texture(u_scene_tex, suv).rgb;
        vec3 baseN = normalize(texture(u_scene_normal_tex, suv).rgb * 2.0 - 1.0);
        vec4 nmap = (u_has_tex == 1) ? texture(u_tex, v_uv) : vec4(0.5, 0.5, 1.0, 1.0);
        vec3 n_ts = vec3(nmap.x * 2.0 - 1.0, nmap.y * 2.0 - 1.0, 0.0);
        n_ts.z = sqrt(max(1.0 - (n_ts.x*n_ts.x + n_ts.y*n_ts.y), 0.0));
        n_ts = normalize(n_ts);
        vec3 decal_n = normalize(n_ts);
        vec3 merged = normalize(decal_n);
        float diff = max(dot(merged, -u_light_dir), 0.0);
        float hl = diff * 0.5 + 0.5;
        vec3 lit = u_ambient + (1.0 - u_ambient) * hl;
        vec3 col = base_albedo * lit;
        col = pow(col, vec3(1.0 / 2.2));
        fragColor = vec4(col, 1.0);
        return;
    }
    fragColor = vec4(base.rgb, base.a * u_opacity);
}
"""

#: FX 单输出（FX 本就单输出，无需变体；此别名便于与其它 program 保持一致）。
FRAG_FX_SINGLE = FRAG_FX

#: ★ INDEXED 专用 shader（u_mode==3）：只声明 indexed 用到的 sampler，纹理单元与 PBS/FS 完全独立，
#:   避免单元冲突（2026-08-27）。材质路径分离第一步。
FRAG_INDEXED = """
#version 400 core
in vec4 v_color;
in vec3 v_normal;
in vec2 v_uv;
uniform int u_mode;
uniform float u_opacity;
uniform vec3 u_light_dir;
uniform vec3 u_ambient;
uniform int u_has_tex;
uniform sampler2D u_matid_tex;
uniform sampler2DArray u_tiles_tex;
uniform sampler2DArray u_normal_tex;
uniform sampler2DArray u_mg_tex;
uniform sampler2D u_alpha_n_map;
uniform sampler2D u_art_tex;
uniform sampler2DArray u_noise_tex;
uniform vec4 u_offset_scale[196];
uniform vec4 u_rotation[196];
uniform vec4 u_tile_idx[196];
uniform vec4 u_tint[196];
uniform vec4 u_remove[196];
uniform float u_gamma;
uniform vec2 u_viewport;
uniform int u_mrt;
uniform int u_debug_mode;
uniform int u_use_scene_normal;
uniform vec3 u_view_dir;   // 观察方向（反射用）
uniform int u_matid_vis;   // 1=输出 matId 伪彩(诊断散块对应材质)
uniform sampler2D u_scene_final_tex;
uniform vec3 u_light_pos;             // 点光源位置（天上）
uniform float u_normal_strength;      // 法线贴图强度（>1 加强凹凸细节）
in vec3 v_world_pos;                  // 世界坐标（点光源用）
out vec4 fragColor;
out vec4 fragNormal;
out vec3 fragWorldPos;                // MRT 附件2：世界坐标（供最终点光源）
// 统一 PBR：Cook-Torrance GGX + Schlick Fresnel 直接光镜面反射（天上的点光源）。
// ★ 已移除程序化天空盒环境反射：金属只反射光源高光，不反射天空/海面色相。
vec3 pbr_light(vec3 albedo, vec3 N, float metallic, float gloss, vec3 lit, vec3 worldPos) {
    vec3 path = u_light_pos - worldPos;
    float dist = max(length(path), 1e-4);
    vec3 L = path / dist;
    float atten = clamp(1.0 / (1.0 + 0.0008 * dist * dist), 0.0, 1.0);
    vec3 V = normalize(u_view_dir);
    vec3 H = normalize(L + V);
    float NdotL = max(dot(N, L), 0.0);
    float NdotV = max(dot(N, V), 0.0);
    float NdotH = max(dot(N, H), 0.0);
    float VdotH = max(dot(V, H), 0.0);
    float roughness = clamp(1.0 - gloss, 0.04, 1.0);
    vec3 F0 = mix(vec3(0.04), albedo, metallic);
    vec3 F = F0 + (1.0 - F0) * pow(1.0 - VdotH, 5.0);
    float a = roughness * roughness; float a2 = a * a;
    float denom = NdotH * NdotH * (a2 - 1.0) + 1.0;
    float D = a2 / max(3.14159265 * denom * denom, 1e-5);
    float k = (roughness + 1.0); k = k * k / 8.0;
    float Gv = NdotV / (NdotV * (1.0 - k) + k);
    float Gl = NdotL / (NdotL * (1.0 - k) + k);
    float G = Gv * Gl;
    vec3 specular = (D * G * F) / max(4.0 * NdotV * NdotL, 1e-5);
    // MG 不影响基础颜色。环境光保底不衰减，点光源贡献随距离衰减。
    vec3 diffuse = albedo * lit;
    vec3 ambient_part = albedo * u_ambient;
    vec3 direct = ambient_part + (diffuse - ambient_part) * atten + specular * NdotL * atten * 2.0;
    return direct;
}
void main() {
    vec4 base = v_color;
    if (u_mode == 3) {
        ivec2 imsz = textureSize(u_matid_tex, 0);
        vec2 noise_uv = v_uv * 48.0;
        vec2 noise_raw = texture(u_noise_tex, vec3(noise_uv, 0.0)).xy;
        float floating = dot(normalize(v_normal), vec3(0.0, 1.0, 0.0));
        vec2 noise_sel = (floating > 0.96) ? vec2(noise_raw.x) : noise_raw;
        vec2 noise2 = noise_sel * 2.0 - 1.0;
        vec2 muv_uv = v_uv + noise2 * (1.0 / (48.0 * 52.0));
        vec2 muv = (floor(muv_uv * vec2(imsz) + 0.5)) / vec2(imsz);
        // ★ 官方 gather4 + 一致性选择（2026-08-27）：取 4 邻材质ID，选「与其余最一致」者，
        //   消除材质分块边界处的零星错误色块（紫色/白色小块）。
        vec4 m4 = textureGather(u_matid_tex, muv, 0);
        vec4 mid4 = min(floor(m4 * 255.0 + 0.5), vec4(195.0));
        float d0 = abs(mid4.x-mid4.y)+abs(mid4.x-mid4.z)+abs(mid4.x-mid4.w);
        float d1 = abs(mid4.y-mid4.x)+abs(mid4.y-mid4.z)+abs(mid4.y-mid4.w);
        float d2 = abs(mid4.z-mid4.x)+abs(mid4.z-mid4.y)+abs(mid4.z-mid4.w);
        float d3 = abs(mid4.w-mid4.x)+abs(mid4.w-mid4.y)+abs(mid4.w-mid4.z);
        float dm = min(min(d0, d1), min(d2, d3));
        float sel = (dm == d0) ? mid4.x : (dm == d1) ? mid4.y : (dm == d2) ? mid4.z : mid4.w;
        int matId = int(sel);
        vec2 uv = v_uv * u_offset_scale[matId].zw + u_offset_scale[matId].xy;
        float uang = u_rotation[matId].x;
        float usa = sin(uang); float uca = cos(uang);
        uv = vec2(uv.x*uca + uv.y*usa, -uv.x*usa + uv.y*uca);
        float slice = max(u_tile_idx[matId].x, 0.0);
        vec2 dudx = dFdx(uv);
        vec2 dudy = dFdy(uv);
        vec3 albedo = textureGrad(u_tiles_tex, vec3(uv, slice), dudx, dudy).rgb;
        float g = u_gamma;
        vec3 albedo_lin = pow(albedo, vec3(g));
        vec3 tint_lin = pow(u_tint[matId].rgb, vec3(g));
        vec3 ref = u_remove[matId].rgb;
        float sum = abs(albedo.x-ref.x) + abs(albedo.y-ref.y) + abs(albedo.z-ref.z);
        float k = clamp((sum + 0.001) / max(u_tint[matId].w, 1e-4), 0.0, 1.0);
        vec3 c = mix(tint_lin, albedo_lin, k);
        // 涂装：烘焙后的 camo 仅对 diffuse 直接覆盖，不影响法线/金属/光泽。
        // 花纹强度 = art alpha(图案遮罩；non-tiled 黑区 α=0 透出底色) × 材质 art 强度。
        float mslice = max(u_tile_idx[matId].z, 0.0);
        vec3 mg = textureGrad(u_mg_tex, vec3(uv, mslice), dudx, dudy).rgb;
        float metallic = mg.r;
        float gloss = mg.g;
        vec4 art4 = texture(u_art_tex, v_uv);
        float am = clamp(art4.a * u_rotation[matId].y, 0.0, 1.0);
        c = mix(c, art4.rgb, am);
        if (u_debug_mode == 5) {
            // 涂装覆盖强度 debug：显示 art alpha × art 强度灰度。
            fragColor = vec4(vec3(am), 1.0);
            return;
        }
        float nslice = max(u_tile_idx[matId].y, 0.0);
        vec3 ntex = textureGrad(u_normal_tex, vec3(uv, nslice), dudx, dudy).rgb;
        vec3 n_ts = vec3(ntex.x * 2.0 - 1.0, ntex.y * 2.0 - 1.0, 0.0);
        float nz = n_ts.x*n_ts.x + n_ts.y*n_ts.y;
        n_ts.z = sqrt(max(1.0 - nz, 0.0));
        vec3 a4 = texture(u_alpha_n_map, v_uv).rgb;
        vec3 n_a = vec3(a4.x * 2.0 - 1.0, a4.y * 2.0 - 1.0, 0.0);
        float nza = n_a.x*n_a.x + n_a.y*n_a.y;
        n_a.z = sqrt(max(1.0 - nza, 0.0));
        n_ts = normalize(n_ts + n_a - vec3(0.0, 0.0, 1.0));
        n_ts.xy *= u_normal_strength;   // ★ 加强法线，突出 _n 凹凸细节
        vec3 n_world = normalize(n_ts);
        if (u_mrt == 1) {
            fragColor = vec4(c, metallic);
            fragNormal = vec4(n_world * 0.5 + 0.5, gloss);
            fragWorldPos = v_world_pos;
        } else {
            if (u_matid_vis == 1) {
                fragColor = vec4(vec3(float(matId) / 195.0), 1.0);
                return;
            }
            if (u_use_scene_normal == 1) {
                vec2 suv2 = gl_FragCoord.xy / u_viewport;
                n_world = normalize(texture(u_scene_final_tex, suv2).rgb * 2.0 - 1.0);
            }
            vec3 litL = normalize(u_light_pos - v_world_pos);   // 点光源方向
            float diff2 = max(dot(n_world, litL), 0.0);
            float hl2 = diff2 * 0.5 + 0.5;
            vec3 lit2 = u_ambient + (1.0 - u_ambient) * hl2;
            c = pbr_light(c, n_world, metallic, gloss, lit2, v_world_pos);
            c = pow(c, vec3(1.0 / 2.2));
            fragColor = vec4(c, 1.0);
        }
        return;
    }
    fragColor = vec4(base.rgb, base.a * u_opacity);
}
"""

#: FRAG_INDEXED 单输出变体（移除 fragNormal 声明与赋值），用于单 drawbuffer 目标。
FRAG_INDEXED_SINGLE = FRAG_INDEXED.replace(
    "out vec4 fragColor;\nout vec4 fragNormal;\nout vec3 fragWorldPos;                // MRT 附件2：世界坐标（供最终点光源）",
    "out vec4 fragColor;",
).replace(
    "            fragColor = vec4(c, metallic);\n            fragNormal = vec4(n_world * 0.5 + 0.5, gloss);\n            fragWorldPos = v_world_pos;",
    "            fragColor = vec4(c, metallic);",
)

#: 每顶点 12 个 float：position(3) + normal(3) + uv(2) + color(4)
_VERTEX_STRIDE = 48
_POS_OFFSET = 0
_NRM_OFFSET = 12
_UV_OFFSET = 24
_COL_OFFSET = 32

_UNIFORMS = ("u_mvp", "u_normal_mat", "u_mode", "u_opacity", "u_light_dir", "u_ambient",
             "u_tex", "u_has_tex", "u_emissive", "u_emissive_k",
             "u_matid_tex", "u_tiles_tex", "u_normal_tex", "u_mg_tex", "u_alpha_n_map", "u_art_tex",
             "u_noise_tex", "u_offset_scale", "u_rotation", "u_tile_idx", "u_tint", "u_remove",
             "u_gamma", "u_scene_tex", "u_scene_normal_tex", "u_viewport", "u_mrt",
             "u_normal_map", "u_has_normal_map", "u_mg_map", "u_has_mg", "u_debug_mode", "u_scene_final_tex", "u_use_scene_normal",
             "u_view_dir", "u_light_pos", "u_normal_strength", "u_scene_world_tex")

#: INDEXED 专用 program 的 uniform 表（与 PBS/FS 独立，避免共用造成的单元/状态冲突）
_UNIFORMS_INDEXED = ("u_mvp", "u_normal_mat", "u_mode", "u_opacity", "u_light_dir", "u_ambient", "u_matid_vis",
                     "u_has_tex", "u_has_normal_map", "u_matid_tex", "u_tiles_tex", "u_normal_tex", "u_mg_tex",
                     "u_alpha_n_map", "u_art_tex", "u_noise_tex", "u_offset_scale", "u_rotation",
                     "u_tile_idx", "u_tint", "u_remove", "u_gamma", "u_viewport", "u_mrt",
                     "u_debug_mode", "u_use_scene_normal", "u_scene_final_tex", "u_view_dir", "u_light_pos", "u_normal_strength")


def _compile_shader(shader_type: int, source: str) -> int:
    sh = GL.glCreateShader(shader_type)
    GL.glShaderSource(sh, source)
    GL.glCompileShader(sh)
    if not GL.glGetShaderiv(sh, GL.GL_COMPILE_STATUS):
        log = GL.glGetShaderInfoLog(sh)
        GL.glDeleteShader(sh)
        try:
            from app.signals import bus
            bus.log_message.emit(f"⚠️ Shader 编译失败: {log}")
        except Exception:
            pass
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
    GL.glBindFragDataLocation(prog, 2, "fragWorldPos")
    GL.glLinkProgram(prog)
    GL.glDeleteShader(vs)
    GL.glDeleteShader(fs)
    if not GL.glGetProgramiv(prog, GL.GL_LINK_STATUS):
        log = GL.glGetProgramInfoLog(prog)
        GL.glDeleteProgram(prog)
        try:
            from app.signals import bus
            bus.log_message.emit(f"⚠️ Program 链接失败: {log}")
        except Exception:
            pass
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
            # ★ 模式区别(2026-08-27)：官方用 mip 过滤采样器(g_genericWrapSampler s5) + sample_d，
            #   textureGrad 按导数选 mip。repeat 的数组纹理(albedoArray/normalArray/rgbNoiseMap)
            #   已上传全部 mip 层(layers 有 11 级)，但此前 MIN_FILTER=LINEAR 导致 textureGrad 只用
            #   base level(全细节) → 船底 v_uv*38 高频平铺层1的板条 → 红白条纹；炮衣 v_uv*6 平铺较
            #   少受 mip 影响小。开启 mip 过滤后：船底高导数→粗糙mip→平滑均匀红，炮衣低导数→精细mip→
            #   保留斜纹。非 repeat 纹理仍用 LINEAR 避免过度模糊。
            n_mips_total = len(dds.layers) if is_array else len(dds.mips)
            if repeat and n_mips_total > 1:
                GL.glTexParameteri(target, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR_MIPMAP_LINEAR)
            else:
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
    if mesh.tech_family == "emissive":
        return True   # 自发光材质：无光照直显（发光叠加 pass），不受 PBR/光照影响
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
        #: 材质贴图集 {键: (vfs_path, bytes)}，供诊断/后续复用
        self.material_textures = material_textures or {}
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
        # instance model matrix（每 mesh 一份 VBO，默认 1 个 identity；多实例时上传 N 个）
        self._inst_vbo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._inst_vbo)
        _id = np.eye(4, dtype=np.float32)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, _id.nbytes, _id, GL.GL_DYNAMIC_DRAW)
        for k in range(4):
            GL.glEnableVertexAttribArray(8 + k)
            GL.glVertexAttribPointer(8 + k, 4, GL.GL_FLOAT, GL.GL_FALSE, 64, _gl_off(k * 16))
            GL.glVertexAttribDivisor(8 + k, 1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
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
                _rep = key in ("albedoArray", "normalArray", "rgbNoiseMap", "MGArray")   # 官方 wrap 采样器
                _nsrgb = ("materialIdMap", "albedoArray", "normalArray", "normalMap", "g_normalMap", "MGArray", "metallicGlossMap")
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

    def render_instanced(self, mode: int, matrices: list, line: bool = False):
        """GPU instancing：一次上传 N 个 model matrix，一次 glDrawElementsInstanced 画所有实例。"""
        ibo = self._line_ibo if line else self._ibo
        count = self._line_count if line else self.index_count
        if count == 0 or not matrices:
            return
        mats = np.zeros((len(matrices), 16), dtype=np.float32)
        for i, m in enumerate(matrices):
            if m is None:
                mats[i] = np.eye(4, dtype=np.float32).reshape(-1)
            else:
                # 列主序存储（.T 展平），与 GLSL mat4(i_model0..3) 的列构造一致
                mats[i] = np.asarray(m, dtype=np.float32).T.reshape(-1)
        GL.glBindVertexArray(self._vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._inst_vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, mats.nbytes, np.ascontiguousarray(mats), GL.GL_DYNAMIC_DRAW)
        GL.glBindBuffer(GL.GL_ELEMENT_ARRAY_BUFFER, ibo)
        GL.glDrawElementsInstanced(mode, count, GL.GL_UNSIGNED_INT, None, len(matrices))
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
        self._prog_indexed = 0       # INDEXED 专用（单输出，直接光照）
        self._unif_indexed = {}
        self._prog_indexed_mrt = 0   # INDEXED 专用（双输出，MRT）
        self._unif_indexed_mrt = {}
        self._prog_fx = 0           # FX/decal/fullscreen 专用（单输出）
        self._unif_fx = {}
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
        self._scene_world_tex: int = 0
        self._scene_depth_rb: int = 0
        self._scene_fbo_size = (0, 0)
        #: 默认帧缓冲是否有可匹配的深度附件（决定能否跨 FBO blit 深度）
        self._depth_blit_ok: bool = True
        # Normal Ping-Pong FBO（独立，避免 feedback loop）
        self._na_fbo: int = 0; self._na_tex: int = 0
        self._nb_fbo: int = 0; self._nb_tex: int = 0
        self._fullscreen_vao: int = 0; self._fullscreen_vbo: int = 0
        #: Debug 模式（N 循环 0..5）：0=正常，1=模型名称，2=最终法线，3=metallic，4=gloss，5=emissive
        self._debug_mode = 0
        #: matId 伪彩诊断（>0 时 INDEXED 输出 matId 值；0=正常渲染）
        self._matid_vis = 0
        #: debug(2/3) 模型点位名称（paintEvent 叠加文本）
        self._mount_labels = []
        #: debug 点位缓存的 GL 资源（_marker_vao/_marker_vbo/_marker_cbo）与数据指纹
        #: —— 点位 VBO/VAO 在 _meshes 变化时重建一次，避免每帧 gen/delete 卡顿。
        self._marker_vao: int = 0
        self._marker_vbo: int = 0
        self._marker_cbo: int = 0
        self._marker_fingerprint: tuple = ()
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
        # ★ mesh 重建时同步释放 debug 点位缓存（旧指纹失效）
        self._release_marker_resources()
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
        # 单输出 PBS program：用于单 drawbuffer 目标（默认 FBO / 透明 / 装甲 / 线框）。
        # 只声明 PBS 用到的 sampler（u_tex/u_normal_map），与 INDEXED/FX 单元独立，避免 1282。
        self._program = _link_program(VERT_SRC, FRAG_PBS_SINGLE)
        for name in _UNIFORMS:
            self._uniforms[name] = GL.glGetUniformLocation(self._program, name)
        # MRT PBS program（fragColor + fragNormal 双输出）：仅 Pass1 渲 scene_fbo(RT0/RT1) 用。
        self._program_mrt = _link_program(VERT_SRC, FRAG_PBS)
        self._uniforms_mrt = {name: GL.glGetUniformLocation(self._program_mrt, name)
                              for name in _UNIFORMS}
        # INDEXED 专用 program（与 PBS/FS 分离，规避纹理单元冲突）
        self._prog_indexed = _link_program(VERT_SRC, FRAG_INDEXED_SINGLE)
        self._unif_indexed = {name: GL.glGetUniformLocation(self._prog_indexed, name)
                              for name in _UNIFORMS_INDEXED}
        self._prog_indexed_mrt = _link_program(VERT_SRC, FRAG_INDEXED)
        self._unif_indexed_mrt = {name: GL.glGetUniformLocation(self._prog_indexed_mrt, name)
                                  for name in _UNIFORMS_INDEXED}
        # FX / decal program（VERT_SRC + FRAG_FX，decal mesh 真实 UV/attrib；单输出）
        self._prog_fx = _link_program(VERT_SRC, FRAG_FX_SINGLE)
        self._unif_fx = {name: GL.glGetUniformLocation(self._prog_fx, name)
                         for name in _UNIFORMS}
        # 独立 fullscreen program（gl_VertexID 全屏三角形，无 VAO/attrib；单输出）
        self._fs_program = _link_program(TEX_VERT_SRC, FRAG_FX_SINGLE)
        self._fs_uniforms = {name: GL.glGetUniformLocation(self._fs_program, name)
                             for name in ("u_mode", "u_viewport", "u_scene_tex",
                                          "u_scene_normal_tex", "u_scene_final_tex",
                                          "u_light_dir", "u_ambient", "u_debug_mode",
                                          "u_view_dir", "u_light_pos", "u_normal_strength",
                                          "u_scene_world_tex")}
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
        GL.glClearColor(0.30, 0.46, 0.60, 1.0)   # 天空背景色
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
        # ★ 光源：u_light_dir 为光照射方向（从天上右前照向模型）。-u_light_dir 即指向太阳的方向。
        GL.glUniform3f(u["u_light_dir"], -0.35, -0.6, -0.72)
        # 点光源优先：环境光压低到仅作保底补充，让点光源的方向性/衰减主导明暗。
        GL.glUniform3f(u["u_ambient"], 0.06, 0.08, 0.10)
        # 点光源位于场景中心上方（天上）；法线强度加强 _n。
        _c0 = self._scene_bounds[0] if self._scene_bounds else np.zeros(3)
        GL.glUniform3f(u["u_light_pos"], float(_c0[0]), float(_c0[1]) + 45.0, float(_c0[2]))
        GL.glUniform1f(u["u_normal_strength"], 1.5)

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
                GL.glClearColor(0.30, 0.46, 0.60, 1.0)   # 天空背景色
                GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
                GL.glDrawBuffers([GL.GL_COLOR_ATTACHMENT0, GL.GL_COLOR_ATTACHMENT1, GL.GL_COLOR_ATTACHMENT2])
                GL.glDisable(GL.GL_BLEND)
                GL.glDepthMask(GL.GL_TRUE)
                # MRT 需双输出 program；用独立 _uniforms_mrt（与 _program 的单输出分离）
                GL.glUseProgram(self._program_mrt)
                um = self._uniforms_mrt
                GL.glUniform3f(um["u_light_dir"], -0.35, -0.6, -0.72)
                GL.glUniform3f(um["u_ambient"], 0.06, 0.08, 0.10)
                _c0 = self._scene_bounds[0] if self._scene_bounds else np.zeros(3)
                GL.glUniform3f(um["u_light_pos"], float(_c0[0]), float(_c0[1]) + 45.0, float(_c0[2]))
                GL.glUniform1f(um["u_normal_strength"], 1.5)
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
                    GL.glUseProgram(self._prog_fx)
                    fx = self._unif_fx
                    GL.glUniform1i(fx["u_mrt"], 0)
                    GL.glUniform1i(fx["u_mode"], 9)
                    GL.glUniform1i(fx["u_use_scene_normal"], 0)
                    GL.glUniform2f(fx["u_viewport"], float(w), float(h))
                    GL.glActiveTexture(GL.GL_TEXTURE1)
                    GL.glBindTexture(GL.GL_TEXTURE_2D, self._na_tex)
                    GL.glUniform1i(fx["u_scene_normal_tex"], 1)
                    GL.glActiveTexture(GL.GL_TEXTURE0)
                    for mesh in decal_overlays:
                        # 逐实例绘制（每实例 bind 材质 + 更新模型矩阵）
                        insts = getattr(mesh, "instance_matrices", None) or []
                        if insts:
                            base = mesh.model_matrix
                            for inst in insts:
                                model = (inst if base is None
                                         else np.ascontiguousarray(base @ inst, dtype=np.float32))
                                self._draw_decal_once(view, proj, fx, mesh, model)
                        else:
                            self._draw_decal_once(view, proj, fx, mesh, mesh.model_matrix)
                    self._apply_model(view, proj, None, fx)
                    GL.glUseProgram(self._program)
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
                # 最终 Lighting：读 Hull Albedo + Final Normal（绑定场景/MRT 纹理）
                GL.glUniform2f(u["u_viewport"], float(w), float(h))
                GL.glActiveTexture(GL.GL_TEXTURE5)
                GL.glBindTexture(GL.GL_TEXTURE_2D, self._scene_color_tex)
                GL.glUniform1i(u["u_scene_tex"], 5)
                GL.glActiveTexture(GL.GL_TEXTURE8)
                GL.glBindTexture(GL.GL_TEXTURE_2D, self._nb_tex)
                GL.glUniform1i(u["u_scene_final_tex"], 8)
                GL.glActiveTexture(GL.GL_TEXTURE0)
                if self._debug_mode == 2:
                    # debug 2：最终法线
                    GL.glUniform1i(u["u_mode"], 12)
                    self._draw_fullscreen(12, w, h)
                elif self._debug_mode == 3:
                    # debug 3：metallic（scene_color_tex.a）
                    GL.glUniform1i(u["u_mode"], 13)
                    self._draw_fullscreen(13, w, h)
                elif self._debug_mode == 4:
                    # debug 4：gloss（nb_tex.a）
                    GL.glUniform1i(u["u_mode"], 14)
                    self._draw_fullscreen(14, w, h)
                else:
                    GL.glUniform1i(u["u_mode"], 11)
                    self._draw_fullscreen(11, w, h)
            # ★ 把 scene 深度拷到默认 FBO：透明 pass（玻璃/线网/螺旋桨等）深度测试需要
            #   船体深度，否则全过 → 模型穿透显示。仅 deferred 路径有 scene 深度。
            if use_surface and self._depth_blit_ok:
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
            GL.glUniform1i(u["u_debug_mode"], 5 if self._debug_mode == 5 else 0)
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
                # 自发光材质：启用自发光 + 强度；其余关闭（仅在 u_mode==2 时由 shader 读取）。
                # ★ u_emissive/u_emissive_k 是 float uniform，须用 glUniform1f。
                if mesh.tech_family == "emissive":
                    GL.glUniform1f(u["u_emissive"], 1.0)
                    GL.glUniform1f(u["u_emissive_k"], float(mesh.emissive_power or 1.0))
                else:
                    GL.glUniform1f(u["u_emissive"], 0.0)
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

            # ── Debug：模型点位/名称叠加（mode 1=所有模型名称，含挂载点位） ──
            if self._debug_mode == 1 and self._meshes:
                self._draw_model_markers(view, proj, self._uniforms, w, h,
                                         mount_only=False)
        except Exception:  # noqa: BLE001 —— 渲染异常不中断 Qt 绘制循环
            import traceback, sys
            tb = traceback.format_exc()
            try:
                from app.signals import bus
                bus.log_message.emit(f"⚠️ 渲染异常: {tb}")
            except Exception:
                pass
            print(tb, file=sys.stderr)
            pass

        GL.glUseProgram(0)

    def _probe_default_depth_format(self) -> int:
        """探测默认帧缓冲的深度缓冲内部格式。

        glBlitFramebuffer(DEPTH) 要求读/写帧缓冲深度格式一致，否则报
        GL_INVALID_OPERATION(1282)。部分平台/驱动的默认 FBO 深度格式为
        DEPTH24_STENCIL8 等（与离屏场景固定的 DEPTH_COMPONENT24 不同），
        导致设备差异：本机正常、他人机器每帧 1282。这里返回默认 FBO 的精确
        深度格式供离屏深度 RBO 匹配；无深度附件时返回 GL_NONE 并关闭 blit。
        只在 _ensure_scene_fbo 建/重建时调用（GL 上下文内）。
        """
        self._depth_blit_ok = False
        try:
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.defaultFramebufferObject())
            obj_type = GL.glGetFramebufferAttachmentParameteriv(
                GL.GL_FRAMEBUFFER, GL.GL_DEPTH_ATTACHMENT,
                GL.GL_FRAMEBUFFER_ATTACHMENT_OBJECT_TYPE)
            if obj_type == GL.GL_RENDERBUFFER:
                name = GL.glGetFramebufferAttachmentParameteriv(
                    GL.GL_FRAMEBUFFER, GL.GL_DEPTH_ATTACHMENT,
                    GL.GL_FRAMEBUFFER_ATTACHMENT_OBJECT_NAME)
                GL.glBindRenderbuffer(GL.GL_RENDERBUFFER, int(name))
                fmt = int(GL.glGetRenderbufferParameteriv(
                    GL.GL_RENDERBUFFER, GL.GL_RENDERBUFFER_INTERNAL_FORMAT))
                GL.glBindRenderbuffer(GL.GL_RENDERBUFFER, 0)
                if fmt:
                    self._depth_blit_ok = True
                    return fmt
        except Exception:  # noqa: BLE001
            pass
        return GL.GL_DEPTH_COMPONENT24

    def _ensure_scene_fbo(self, w: int, h: int):
        """创建/重建离屏 MRT FBO（未打光 albedo + 世界法线 + 深度）。

        轻量局部 deferred compositing：船体 surface 渲到此 MRT，供 decal_tech
        读取覆盖位置的船体 albedo/世界法线，在光照前合成 decal 法线。
        附件0=albedo(RGBA8 linear)，附件1=世界法线(RGBA8 [0,1] 编码)，深度=默认 FBO 深度格式。
        """
        if self._scene_fbo and self._scene_fbo_size == (w, h):
            return True   # ★ 已存在且尺寸匹配：必须返回 True，否则 use_surface 变 falsy，
                          #   导致后续帧（如旋转相机）跳过 deferred 路径，走 _draw_ship_solid(非MRT) 报 1282
        if self._scene_fbo:
            GL.glDeleteFramebuffers(1, [self._scene_fbo])
            GL.glDeleteTextures([self._scene_color_tex, self._scene_normal_tex, self._scene_world_tex, self._na_tex, self._nb_tex])
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
        # 世界坐标附件(RGBA32F)：Pass1 存 hull 世界坐标，供最终点光源(位置+衰减)打光重建位置。
        self._scene_world_tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._scene_world_tex)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA32F, w, h, 0,
                        GL.GL_RGBA, GL.GL_FLOAT, None)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_NEAREST)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_NEAREST)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
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
        # ★ 用默认 FBO 的深度格式，保证 glBlitFramebuffer(DEPTH) 读/写格式一致，避免 1282。
        self._scene_depth_rb = GL.glGenRenderbuffers(1)
        GL.glBindRenderbuffer(GL.GL_RENDERBUFFER, self._scene_depth_rb)
        GL.glRenderbufferStorage(GL.GL_RENDERBUFFER, self._probe_default_depth_format(), w, h)
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
        GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT2,
                                  GL.GL_TEXTURE_2D, self._scene_world_tex, 0)
        GL.glFramebufferRenderbuffer(GL.GL_FRAMEBUFFER, GL.GL_DEPTH_ATTACHMENT,
                                     GL.GL_RENDERBUFFER, self._scene_depth_rb)
        GL.glDrawBuffers([GL.GL_COLOR_ATTACHMENT0, GL.GL_COLOR_ATTACHMENT1, GL.GL_COLOR_ATTACHMENT2])
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
        prev_prog = None
        last_uu = u
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
            # ★ 按材质类型选独立 program（indexed 与 PBS 纹理单元互不干扰）
            if getattr(mesh, "tech_family", "") == "indexed":
                prog = self._prog_indexed_mrt if mrt_surface else self._prog_indexed
                uu = self._unif_indexed_mrt if mrt_surface else self._unif_indexed
            else:
                prog = self._program_mrt if mrt_surface else self._program
                uu = self._uniforms_mrt if mrt_surface else self._uniforms
            if prog != prev_prog:
                GL.glUseProgram(prog)
                prev_prog = prog
                GL.glUniform1i(uu["u_mode"], 0)
                GL.glUniform1i(uu["u_debug_mode"], 5 if self._debug_mode == 5 else 0)
                GL.glUniform1f(uu["u_opacity"], 1.0)
                GL.glUniform3f(uu["u_light_dir"], -0.35, -0.6, -0.72)
                GL.glUniform3f(uu["u_ambient"], 0.06, 0.08, 0.10)
                _c0 = self._scene_bounds[0] if self._scene_bounds else np.zeros(3)
                GL.glUniform3f(uu["u_light_pos"], float(_c0[0]), float(_c0[1]) + 45.0, float(_c0[2]))
                GL.glUniform1f(uu["u_normal_strength"], 1.5)
                GL.glUniform1f(uu.get("u_emissive", -1), 0.0)
                GL.glUniform1f(uu.get("u_emissive_k", -1), 1.0)
                GL.glUniform1i(uu.get("u_tex", -1), 0)
                GL.glUniform1i(uu["u_mrt"], 1 if mrt_surface else 0)
                GL.glActiveTexture(GL.GL_TEXTURE0)
            last_uu = uu
            self._apply_model(view, proj, None, uu)
            self._bind_solid_material(uu, mesh)
            self._emit_instances(view, proj, mesh, u=uu)
        self._apply_model(view, proj, None, last_uu)
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
        # _mg（metallicGlossMap）绑定到单元 5（R=metallic, G=gloss, B=发光/涂装强度）
        _mgid = 0
        if mesh._extra_tex:
            _mgid = mesh._extra_tex.get("metallicGlossMap", 0)
        if _mgid:
            GL.glActiveTexture(GL.GL_TEXTURE5)
            GL.glBindTexture(GL.GL_TEXTURE_2D, _mgid)
            GL.glUniform1i(u["u_mg_map"], 5)
            GL.glUniform1i(u["u_has_mg"], 1)
        else:
            GL.glUniform1i(u["u_has_mg"], 0)
        _vd = self._camera.eye() - self._camera.target
        _nv = _vd / max(float(np.linalg.norm(_vd)), 1e-6)
        GL.glUniform3f(u["u_view_dir"], float(_nv[0]), float(_nv[1]), float(_nv[2]))
        # ★ 关键：法线贴图绑到单元 6 后，必须把活动纹理单元切回 0，
        #   否则下一个网格的 diffuse 会绑到单元 6，而 u_tex 仍采样单元 0 → 串贴图。
        GL.glActiveTexture(GL.GL_TEXTURE0)

    def _emit_instances(self, view, proj, mesh, line=False, u=None):
        """逐实例绘制：多实例用 GPU Instancing（1 次 glDrawElementsInstanced），单实例直接 draw。"""
        matrices = _emit_matrices(mesh)
        if not matrices:
            return
        if len(matrices) == 1:
            self._apply_model(view, proj, matrices[0], u)
            mesh.render(GL.GL_TRIANGLES if not line else GL.GL_LINES, line=line)
            return
        self._apply_model(view, proj, None, u)
        mesh.render_instanced(GL.GL_TRIANGLES if not line else GL.GL_LINES, matrices, line=line)

    @staticmethod
    def _bind_alpha_material(u, mesh):
        """透明/贴花单次材质绑定（uniform + 贴图）——每个网格只做一次。

        ★ 关键修复：shader 里声明了 sampler2DArray 的 u_tiles_tex/u_normal_tex/u_noise_tex
        （INDEXED 用）。若它们默认绑到 unit0，而本 pass 把 mesh._texture(sampler2D 的 2D 纹理)
        也绑到 unit0，则「sampler2DArray 绑 2D 纹理」→ GL_INVALID_OPERATION(1282)。
        故把它们指到独立空 unit(8/9/10) 并绑空 2D_ARRAY，避免与 u_tex 冲突。
        """
        # 把 INDEXED 用的 sampler2DArray 挪到独立 unit，避免与 unit0 的 2D 纹理类型冲突
        for _nm, _un in (("u_tiles_tex", 8), ("u_normal_tex", 9), ("u_noise_tex", 10)):
            if u.get(_nm) is not None and u[_nm] >= 0:
                GL.glUniform1i(u[_nm], _un)
                GL.glActiveTexture(GL.GL_TEXTURE0 + _un)
                GL.glBindTexture(GL.GL_TEXTURE_2D_ARRAY, 0)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        if mesh.has_tex:
            GL.glBindTexture(mesh._texture_target, mesh._texture)
            GL.glUniform1i(u["u_has_tex"], 1)
        else:
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
            GL.glUniform1i(u["u_has_tex"], 0)
        # 自发光材质：绑定 _mg (metallicGlossMap) 到 unit5，B 通道作 emissive mask
        _mgid = (mesh._extra_tex or {}).get("metallicGlossMap", 0)
        if _mgid:
            GL.glActiveTexture(GL.GL_TEXTURE5)
            GL.glBindTexture(GL.GL_TEXTURE_2D, _mgid)
            GL.glUniform1i(u["u_mg_map"], 5)
            GL.glUniform1i(u["u_has_mg"], 1)
        else:
            GL.glUniform1i(u["u_has_mg"], 0)
        GL.glActiveTexture(GL.GL_TEXTURE0)

    def _draw_alpha_once(self, view, proj, u, mesh, model):
        """透明 pass 单次绘制一个网格（应用模型矩阵 + 绑定贴图）。"""
        GL.glUseProgram(self._program)
        self._apply_model(view, proj, model, u)
        self._bind_alpha_material(u, mesh)
        try:
            mesh.render(GL.GL_TRIANGLES)
        except GLError:
            raise

    def _draw_decal_once(self, view, proj, u, mesh, model):
        """贴花（dec_tech/amgn）单次绘制一个网格（应用模型矩阵 + 绑定贴图）。"""
        GL.glUseProgram(self._prog_fx)
        self._apply_model(view, proj, model, u)
        self._bind_alpha_material(u, mesh)
        try:
            mesh.render(GL.GL_TRIANGLES)
        except GLError:
            raise

    def _draw_model_markers(self, view, proj, u, w, h, mount_only: bool):
        """debug(2/3)：显示模型点位 + 名称（挂载为黄点，船体等为青点）。

        mount_only=True：只显示挂载模型点位（mode 2）；
        mount_only=False：显示所有渲染模型(Hull/Mount)中心点与名称（mode 3）。
        名称投影到屏幕记录到 self._mount_labels，由 paintEvent 叠加文本。

        ★ 性能：点位 VBO/VAO 按数据指纹缓存，_meshes 不变时复用（不再每帧 gen/delete）；
          ✅ 去重：同一位置只保留一个点+一个名称，避免「每个节点渲染两遍」。
          ✅ 向量化投影：名称投影用 numpy 批量计算，替代逐点 Python 循环。
        """
        def _label_for(m):
            """模式 1 显示各模型自身形状名/骨骼节点名（替代几何文件名）。"""
            if getattr(self, '_debug_mode', 0) == 1:
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
        seen = set()           # (x,y,z) 去重：同一位置只标一次，解决「渲染两遍」
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
            label = _label_for(m)
            # 挂载=黄，船体=青
            clr = (1.0, 0.9, 0.2, 1.0) if m.kind == "mount" else (0.3, 0.8, 1.0, 1.0)
            coords = []
            if insts:
                base = mm
                for inst in insts:
                    wm = (inst if base is None else base @ inst)
                    p = wm @ np.array([cx, cy, cz, 1.0], dtype=np.float64)
                    coords.append((float(p[0]), float(p[1]), float(p[2])))
            else:
                if mm is not None:
                    coords.append((float(mm[0, 3]), float(mm[1, 3]), float(mm[2, 3])))
                else:
                    coords.append((cx, cy, cz))
            for (x, y, z) in coords:
                key = (round(x, 4), round(y, 4), round(z, 4))   # 坐标容差去重
                if key in seen:
                    continue
                seen.add(key)
                pts.append((x, y, z))
                cols.append(clr)
                names.append((x, y, z, label))
        self._mount_labels = []
        if not pts:
            return
        pos = np.asarray(pts, dtype=np.float32).reshape(-1, 3)
        col = np.asarray(cols, dtype=np.float32).reshape(-1, 4)

        # ★ 向量化投影：一次性算全部点位屏幕坐标（替代逐点 Python 循环）
        try:
            n = pos.shape[0]
            hom = np.concatenate([pos, np.ones((n, 1), dtype=np.float64)], axis=1)
            mvp = proj @ view
            clip = (mvp @ hom.T).T          # (n,4)
            wc = clip[:, 3]
            ok = wc > 1e-6
            if np.any(ok):
                ndc = clip[ok, :3] / wc[ok, None]
                sx = (ndc[:, 0] * 0.5 + 0.5) * w
                sy = (1.0 - (ndc[:, 1] * 0.5 + 0.5)) * h
                inb = (-w < sx) & (sx < w * 2) & (-h < sy) & (sy < h * 2)
                idxs = np.where(ok)[0][inb]
                for i in idxs:
                    # 名称取该点对应网格标签（用原 pts 索引，名称可能同点不同）
                    self._mount_labels.append((float(sx[i]), float(sy[i]), names[i][3]))
        except Exception:
            self._mount_labels = []

        # ★ 缓存点位 VBO/VAO：数据指纹(位置+颜色)不变则复用，不再每帧 gen/delete
        fp = (pos.tobytes(), col.tobytes())
        if fp != self._marker_fingerprint:
            self._release_marker_resources()
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
            self._marker_vao, self._marker_vbo, self._marker_cbo = vao, vbo, cbo
            self._marker_fingerprint = fp

        n = pos.shape[0]
        if not (self._marker_vao and n):
            return
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glDisable(GL.GL_BLEND)
        GL.glUniform1i(u["u_mode"], 1)      # 无光照直显颜色
        GL.glUniform1i(u["u_has_tex"], 0)
        GL.glUniform1f(u["u_opacity"], 1.0)
        self._apply_model(view, proj, None)
        GL.glPointSize(6.0)
        GL.glBindVertexArray(self._marker_vao)
        GL.glDrawArrays(GL.GL_POINTS, 0, n)
        GL.glBindVertexArray(0)
        GL.glPointSize(1.0)
        GL.glEnable(GL.GL_DEPTH_TEST)

    def _release_marker_resources(self):
        """释放 debug 点位缓存的 GL 资源。"""
        if self._marker_vao:
            GL.glDeleteVertexArrays(1, [self._marker_vao])
            self._marker_vao = 0
        if self._marker_vbo or self._marker_cbo:
            GL.glDeleteBuffers(2, [self._marker_vbo, self._marker_cbo])
            self._marker_vbo = 0
            self._marker_cbo = 0
        self._marker_fingerprint = ()

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
        GL.glActiveTexture(GL.GL_TEXTURE7)
        GL.glBindTexture(GL.GL_TEXTURE_2D_ARRAY, ex.get("MGArray", 0))
        GL.glUniform1i(u["u_mg_tex"], 7)

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
        # ★ offsetScaleMatIdArr.zw 是**逐材质**的真实 UV 变换倍率（船体 matId23=38，炮塔=20，
        #   各不相同），shader 用 uv = v_uv*scale + offset（原始值，**不取倒数**）采样 tile，
        #   靠 sampler 的 REPEAT wrap 回 [0,1]。勿全局用 "1-v" 翻转（会破坏炮塔平铺）。
        _os = _arr("offsetScaleMatIdArr")
        if _os.size >= 196 * 4:
            GL.glUniform4fv(u["u_offset_scale"], 196, np.ascontiguousarray(_os.reshape(-1)))
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
        GL.glUniform1i(u["u_matid_vis"], 1 if getattr(self, "_matid_vis", 0) else 0)
        # 观察方向（PBR 反射用）
        _vd = self._camera.eye() - self._camera.target
        _nv = _vd / max(float(np.linalg.norm(_vd)), 1e-6)
        GL.glUniform3f(u["u_view_dir"], float(_nv[0]), float(_nv[1]), float(_nv[2]))
        GL.glActiveTexture(GL.GL_TEXTURE0)

    def _draw_fullscreen(self, mode, w, h):
        """用独立 fullscreen program（gl_VertexID 生成 NDC 三角形，无 VAO/attrib）渲全屏。"""
        GL.glUseProgram(self._fs_program)
        fu = self._fs_uniforms
        GL.glUniform1i(fu["u_mode"], mode)
        GL.glUniform1i(fu["u_debug_mode"], 0)   # 法线显示/光照不依赖 shader debug
        GL.glUniform2f(fu["u_viewport"], float(w), float(h))
        GL.glUniform3f(fu["u_light_dir"], -0.35, -0.6, -0.72)
        GL.glUniform3f(fu["u_ambient"], 0.06, 0.08, 0.10)
        GL.glUniform1i(fu["u_scene_tex"], 5)
        GL.glUniform1i(fu["u_scene_normal_tex"], 1)
        GL.glUniform1i(fu["u_scene_final_tex"], 8)
        # 点光源：world 坐标纹理绑到 unit7，供最终打光重建世界位置
        _c0 = self._scene_bounds[0] if self._scene_bounds else np.zeros(3)
        GL.glUniform3f(fu["u_light_pos"], float(_c0[0]), float(_c0[1]) + 45.0, float(_c0[2]))
        GL.glUniform1f(fu["u_normal_strength"], 1.5)
        GL.glUniform1i(fu["u_scene_world_tex"], 7)
        GL.glActiveTexture(GL.GL_TEXTURE7)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._scene_world_tex)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        # 观察方向 + 天空盒（反射环境）绑定到 unit6
        _vd = self._camera.eye() - self._camera.target
        _nv = _vd / max(float(np.linalg.norm(_vd)), 1e-6)
        GL.glUniform3f(fu["u_view_dir"], float(_nv[0]), float(_nv[1]), float(_nv[2]))
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
        # debug(1/2/3/4)：叠加模型点位名称
        if self._debug_mode == 1 and self._mount_labels:
            painter = QPainter(self)
            painter.setPen(QColor(255, 230, 0))
            f = painter.font()
            f.setPointSize(8)
            painter.setFont(f)
            for sx, sy, name in self._mount_labels:
                painter.drawText(int(sx) + 4, int(sy) - 4, name)
            painter.end()

    def keyPressEvent(self, event):
        """Debug 切换：N 循环 0..5。0=正常，1=模型名称，2=最终法线，3=metallic，4=gloss，5=涂装覆盖强度。F12=截图到 _temp/。"""
        k = event.key()
        if k == Qt.Key_F12:
            self._capture_png()
            return
        if k == Qt.Key_N:
            self._debug_mode = (self._debug_mode + 1) % 6
            self.update()
            return
        mapping = {Qt.Key_0: 0, Qt.Key_Escape: 0,
                   Qt.Key_1: 1, Qt.Key_2: 2,
                   Qt.Key_3: 3, Qt.Key_4: 4, Qt.Key_5: 5}
        if k in mapping:
            self._debug_mode = mapping[k]
            self.update()
            return
        super().keyPressEvent(event)

    def _capture_png(self):
        """截取当前视口帧并保存到 _temp/render_<n>.png（F12 触发）。"""
        try:
            from pathlib import Path
            out = Path(__file__).resolve().parents[1] / "_temp"
            out.mkdir(parents=True, exist_ok=True)
            import time
            p = out / f"render_{int(time.time())}.png"
            img = self.grabFramebuffer()
            img.save(str(p))
            from app.signals import bus
            bus.log_message.emit(f"📸 已存截图: {p}")
        except Exception as exc:  # noqa: BLE001
            from app.signals import bus
            bus.log_message.emit(f"⚠️ 截图失败: {exc}")

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
