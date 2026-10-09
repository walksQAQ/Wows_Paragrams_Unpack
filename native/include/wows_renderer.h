/*
 * wows_renderer.h —— WoWS 模型查看器 D3D11 渲染后端（C ABI，唯一公共头）
 *
 * 设计约定（详见 todo_list/New_function_of_d3d11_renderer.md）：
 *   - 纯 C ABI，供 Python ctypes 调用；句柄不透明。
 *   - 所有函数返回 int32_t：0 = WSR_OK，负值 = 错误码。
 *   - 所有结构体首字段 struct_size，便于后续扩展；不使用 bool。
 *   - 字符串一律 UTF-8 / NUL 结尾，调用期间有效，DLL 内部拷贝。
 *   - 线程约定：必须在创建 renderer 的同一线程调用（Qt 主线程）。
 *   - CPU 侧资源描述必须始终驻留（设备丢失重建依赖它，见架构文档 §11.2）。
 *
 * P0 阶段仅覆盖：设备/交换链生命周期、resize、DPI、单帧绘制、设备丢失恢复。
 * 场景 / 纹理 / 材质接口在 P1+ 增加。
 */

#ifndef WOWS_RENDERER_H
#define WOWS_RENDERER_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#if defined(_WIN32)
#  define WSR_API __declspec(dllexport)
#else
#  define WSR_API
#endif

/* ---------- 错误码 ---------- */
#define WSR_OK                  0
#define WSR_ERR_INVALID_ARG   (-1)
#define WSR_ERR_DEVICE        (-2)
#define WSR_ERR_SWAPCHAIN     (-3)
#define WSR_ERR_OUT_OF_MEMORY (-4)
#define WSR_ERR_SHADER        (-5)
#define WSR_ERR_INTERNAL      (-6)

/* ---------- 创建标志 ---------- */
#define WSR_FLAG_NONE          0u
/* 关闭垂直同步（Present(0,0)）；默认 vsync 开启 */
#define WSR_FLAG_NO_VSYNC      1u
/* 使用 DXGI_SWAP_EFFECT_DISCARD 而非 FLIP_DISCARD（兼容 / 降级路径） */
#define WSR_FLAG_LEGACY_BITBLT 2u
/* 启用 deferred 链（MRT + 全屏光照）。默认关闭：该链在“启用后画面退化为全屏均匀色”
 * 的问题解决前，默认走已验证可用的直出路径（几何/材质/装甲/透明均正常）。 */
#define WSR_FLAG_DEFERRED      8u

/* 不透明句柄 */
typedef struct wsr_renderer wsr_renderer;

/* ---------- 结构体 ---------- */
typedef struct wsr_stats {
    uint32_t struct_size;
    uint32_t draw_calls;
    uint32_t device_lost_count;
    uint32_t frame_index;
    float    frame_ms_last;
    float    frame_ms_avg;
} wsr_stats;

typedef struct wsr_options {
    uint32_t struct_size;
    float    clear_color[4];
} wsr_options;

/* ---------- 生命周期 ---------- */
/* hwnd 为窗口句柄（Qt: int(widget.winId())）；width/height 为逻辑尺寸。 */
WSR_API int32_t wsr_create(void *hwnd, uint32_t width, uint32_t height,
                           uint32_t flags, wsr_renderer **out);

WSR_API void    wsr_destroy(wsr_renderer *r);

/* 逻辑尺寸变化；内部按 dpi_scale 换算后备缓冲像素尺寸。 */
WSR_API int32_t wsr_resize(wsr_renderer *r, uint32_t width, uint32_t height);

/* 逻辑像素 → 物理像素的缩放（Qt: widget.devicePixelRatio()）。 */
WSR_API int32_t wsr_set_dpi_scale(wsr_renderer *r, float scale);

WSR_API int32_t wsr_set_options(wsr_renderer *r, const wsr_options *opt);

/* ---------- 帧 ---------- */
WSR_API int32_t wsr_render(wsr_renderer *r);
WSR_API int32_t wsr_stats_get(wsr_renderer *r, wsr_stats *out);

/* ---------- 顶点（48 字节，与旧版 _vdata 布局一致：pos/normal/uv/color） ---------- */
typedef struct wsr_vertex {
    float pos[3];
    float normal[3];
    float uv[2];
    float color[4];
} wsr_vertex;

/* ---------- mesh 归属 ---------- */
#define WSR_MESH_HULL  0u
#define WSR_MESH_MOUNT 1u
#define WSR_MESH_ARMOR 2u

/* ---------- 材质族（决定 shader 路径与 pass 归属） ---------- */
#define WSR_FAM_SOLID        0u  /* 标准 PBS（不透明实体） */
#define WSR_FAM_INDEXED      1u  /* INDEXED 分块材质 */
#define WSR_FAM_EMISSIVE     2u  /* 自发光：无光照直显 + emissive_k 增益 */
#define WSR_FAM_UNLIT        3u  /* grid/glass/透明贴花：无光照直显 + alpha 混合 */
#define WSR_FAM_DECAL_NORMAL 4u  /* 仅提供法线的叠加层（不输出颜色） */

/* ---------- 纹理槽（与 wsr_mesh_desc::textures 索引对应） ---------- */
#define WSR_TEX_DIFFUSE  0
#define WSR_TEX_NORMAL   1
#define WSR_TEX_MG       2
#define WSR_TEX_MATID    3
#define WSR_TEX_TILES_A  4
#define WSR_TEX_TILES_N  5
#define WSR_TEX_TILES_MG 6
#define WSR_TEX_ART      7
#define WSR_TEX_NOISE    8
#define WSR_TEX_ALPHA_N  9
#define WSR_TEX_COUNT    10

/* ---------- mesh 标志 ---------- */
#define WSR_MESHF_NONE           0u
#define WSR_MESHF_NO_DEPTH_WRITE 1u
#define WSR_MESHF_LINES          4u   /* 以 LINELIST 拓扑绘制（装甲板边界线等） */

/* ---------- 纹理上传 ---------- */
#define WSR_TEXKIND_2D       0u
#define WSR_TEXKIND_2D_ARRAY 1u

#define WSR_TEXF_SRGB   1u   /* 颜色贴图：硬件 sRGB 解码 */
#define WSR_TEXF_REPEAT 2u   /* wrap 采样 */
#define WSR_TEXF_POINT  4u   /* 点采样（materialIdMap 等离散数据） */
#define WSR_TEXF_NOMIP  8u   /* 不使用 mip 过滤 */

/*
 * 纹理描述。数据必须是「D3D 期望布局」的压缩/未压缩字节：
 * 2D_ARRAY 的每 mip 内各 slice 连续（mip-major），由调用方（Python）完成
 * layer-major → mip-major 重排（沿用 models/dds_reader.py 的既有修正）。
 */
typedef struct wsr_texture_desc {
    uint32_t struct_size;
    uint32_t kind;        /* WSR_TEXKIND_* */
    uint32_t format;      /* DXGI_FORMAT 值 */
    uint32_t width;
    uint32_t height;
    uint32_t array_size;  /* 2D 时为 1 */
    uint32_t mip_count;
    uint32_t flags;       /* WSR_TEXF_* */
    const void *data;
    uint64_t data_size;
    const uint32_t *mip_offsets;  /* mip_count 项：每 mip 在 data 中的起始偏移 */
    const uint32_t *mip_sizes;    /* mip_count 项：每 mip 字节数（含全部 slice） */
} wsr_texture_desc;

/* ---------- 场景描述 ---------- */
typedef struct wsr_mesh_desc {
    uint32_t struct_size;
    const char *key;              /* 稳定唯一键（可见性/调试/拾取用） */
    uint32_t kind;                /* WSR_MESH_* */
    uint32_t family;              /* WSR_FAM_* */
    uint32_t flags;               /* WSR_MESHF_* */

    const wsr_vertex *vertices;
    uint32_t vertex_count;
    const uint32_t *indices;
    uint32_t index_count;

    const float *model_matrix;        /* 16 float 行主序；NULL = 单位阵 */
    const float *instance_matrices;   /* instance_count × 16 行主序；NULL/0 = 非实例化 */
    uint32_t instance_count;

    float opacity;                    /* 1.0 = 不透明 */
    float emissive_k;                 /* 自发光强度 */

    /* 纹理 key（已 wsr_texture_upload 注册）；NULL/空 = 该通道未声明 */
    const char *textures[WSR_TEX_COUNT];

    /* INDEXED 逐材质数组（各 matid_count×4 float）；非 INDEXED 家族可为 NULL */
    uint32_t matid_count;
    const float *arr_offset_scale;
    const float *arr_rotation;
    const float *arr_tile_idx;
    const float *arr_tint;
    const float *arr_remove;
} wsr_mesh_desc;

/* ---------- 帧参数（相机 + 光照） ---------- */
typedef struct wsr_frame_params {
    uint32_t struct_size;
    float view[16];          /* 行主序（数学矩阵，内部不转置） */
    float proj[16];          /* 行主序；需已修正为 D3D 的 z ∈ [0,1] */
    float light_pos[3];
    float light_dir[3];
    float ambient[3];
    float normal_strength;
    float opacity;
    uint32_t debug_mode;     /* 0=正常 1=模型名 2=法线 3=F0权重 4=粗糙度 5=涂装强度 */

    /* ---- 渲染风格（2026-10-09 新增）----
     * 旧宿主（不填这组字段）会在 wsr_frame_set 里被判 struct_size 不匹配而拒绝，
     * 避免新字段被静默丢弃后出现「参数不生效」的莫名现象。 */
    uint32_t lighting_mode;  /* 0=游戏原版（逐行搬运）1=Studio PBR（程序化环境 + IBL + 曝光） */
    uint32_t normal_space;   /* 0=切线空间法线直接当世界法线（原版行为）1=正确 TBN */
    float    env_strength;   /* Studio：环境亮度（默认 1.0） */
    float    exposure;       /* Studio：曝光（默认 1.0） */
    float    camera_pos[3];  /* Studio：相机世界坐标（镜面 V 向量）；非 Studio 模式不用 */
    uint32_t uv_flip;        /* 纹理 V 轴：0=不翻转（默认，与 GL 参考一致）1=旧行为（翻转，供 A/B） */
} wsr_frame_params;

/* ---------- 视图选项 ---------- */
typedef struct wsr_view_options {
    uint32_t struct_size;
    uint32_t show_hull;
    uint32_t show_mounts;
    uint32_t show_armor;
    uint32_t wireframe;
    uint32_t show_edges;
    float    armor_opacity;
    float    clear_color[4];
} wsr_view_options;

/* ---------- 场景 / 纹理 ---------- */
WSR_API int32_t wsr_texture_upload(wsr_renderer *r, const char *key,
                                   const wsr_texture_desc *desc);
WSR_API int32_t wsr_texture_clear(wsr_renderer *r);

WSR_API int32_t wsr_scene_begin(wsr_renderer *r);
WSR_API int32_t wsr_scene_add_mesh(wsr_renderer *r, const wsr_mesh_desc *desc);
WSR_API int32_t wsr_scene_end(wsr_renderer *r);
WSR_API int32_t wsr_scene_clear(wsr_renderer *r);

WSR_API int32_t wsr_frame_set(wsr_renderer *r, const wsr_frame_params *p);
WSR_API int32_t wsr_view_options_set(wsr_renderer *r, const wsr_view_options *o);

WSR_API int32_t wsr_mesh_set_visible(wsr_renderer *r, const char *key, uint32_t visible);
/* 动态替换索引（装甲可见性过滤 / 高亮叠加） */
WSR_API int32_t wsr_mesh_set_indices(wsr_renderer *r, const char *key,
                                     const uint32_t *indices, uint32_t count);
/* 高亮索引（独立 IB，按需重画一遍：法线偏移 + 纯色） */
WSR_API int32_t wsr_mesh_set_highlight(wsr_renderer *r, const char *key,
                                       const uint32_t *indices, uint32_t count);

WSR_API int32_t wsr_scene_stats(wsr_renderer *r, uint32_t *mesh_count,
                                uint32_t *texture_count);

/* 设备丢失重建后返回 1：调用方必须重新提交纹理与场景（CPU 侧描述为权威副本）。 */
WSR_API int32_t wsr_needs_resubmit(wsr_renderer *r);

/* 抓取当前后备缓冲到 32bpp BMP（A/B 截图验证用；无需外部编码库）。 */
WSR_API int32_t wsr_capture_bmp(wsr_renderer *r, const char *path);

/* 诊断：位标志。bit0=vs bit1=ps bit2=ps_mrt bit3=vs_fs bit4=ps_fs
 * bit5=MRT 三附件就绪 bit6=na/nb 就绪 bit7=布局 bit8=常量缓冲。 */
WSR_API int32_t wsr_diag_state(wsr_renderer *r, uint32_t *flags);

/* ---------- 诊断 ---------- */
/* 最近一次错误的文本描述（线程局部缓冲，无需释放）。 */
WSR_API const char *wsr_last_error(void);

/* P0 调试：模拟设备丢失（驱动重置），用于验证恢复链路；后续保留为调试工具。 */
WSR_API int32_t wsr_debug_simulate_device_lost(wsr_renderer *r);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* WOWS_RENDERER_H */
