/*
 * renderer.cpp —— D3D11 渲染后端实现。
 *
 * 覆盖：
 *   - Device / SwapChain / RenderTarget(+Depth) 生命周期，resize / DPI
 *   - 纹理上传（2D / 2D_ARRAY，压缩字节直传）
 *   - 场景提交（mesh + 材质描述）与逐帧绘制
 *   - 设备丢失最小重建链路：释放 GPU 资源 → 重建 Device/SwapChain/RTV/DSV
 *     → 从 CPU 侧描述重放（不做增量/局部恢复，见架构文档 §11.2）
 *
 * 搬运原则：着色公式只换语言不换算法（架构文档 §1.4）；
 * 参数命名遵循 §5.4.1（`_mg.R` 是 F0 混合权重，不是 metallic）。
 */

#include "wows_renderer.h"

#include <windows.h>

#include <d3d11.h>
#include <dxgi1_2.h>
#include <wrl/client.h>

#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <new>
#include <string>
#include <unordered_map>
#include <vector>

/* 构建期由 fxc 生成（见 CMakeLists.txt 的 wows_compile_shader） */
#include "material_vs.h"
#include "material_ps.h"
#include "material_ps_mrt.h"
#include "fullscreen_vs.h"
#include "fullscreen_ps.h"

using Microsoft::WRL::ComPtr;

namespace {

/* ---------- 错误文本（线程局部） ---------- */
thread_local std::string g_last_error;

int32_t fail(int32_t code, const char *fmt, ...)
{
    char buf[512];
    va_list args;
    va_start(args, fmt);
    vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);
    g_last_error = buf;
    return code;
}

void set_error(const char *fmt, ...)
{
    char buf[512];
    va_list args;
    va_start(args, fmt);
    vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);
    g_last_error = buf;
}

/* ---------- 内部资源结构 ---------- */

static const uint32_t INDEXED_ARRAY_N = 196;
static const uint32_t VERTEX_STRIDE = sizeof(wsr_vertex);   /* 48 */

struct TextureRes {
    ComPtr<ID3D11ShaderResourceView> srv;
    uint32_t kind = WSR_TEXKIND_2D;
};

struct MaterialRes {
    uint32_t family = WSR_FAM_SOLID;
    uint32_t flags = WSR_MESHF_NONE;
    float    opacity = 1.0f;
    float    emissive_k = 1.0f;
    std::string tex[WSR_TEX_COUNT];
    uint32_t matid_count = 0;
    std::vector<float> offset_scale;
    std::vector<float> rotation;
    std::vector<float> tile_idx;
    std::vector<float> tint;
    std::vector<float> remove;
};

struct MeshRes {
    std::string  key;
    uint32_t     kind = WSR_MESH_HULL;
    MaterialRes  mat;

    ComPtr<ID3D11Buffer> vb;
    ComPtr<ID3D11Buffer> ib;
    ComPtr<ID3D11Buffer> inst_vb;

    uint32_t index_count = 0;
    uint32_t vertex_count = 0;
    uint32_t instance_count = 0;
    bool     visible = true;
    bool     has_model = false;
    float    model[16] = { 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1 };
};

/* ---------- 常量缓冲布局（与 material.hlsl 一一对应） ---------- */
struct FrameCBData {
    float mvp[16];          /* proj*view*model（单次绘制）；实例化时 = proj*view */
    float normal_mat[16];
    float light_dir[4];
    float ambient[4];
    float light_pos[4];
    float view_dir[4];
    float params[4];        /* x=normal_strength y=opacity z=emissive_k w=emissive_on */
    float params2[4];       /* x=mode y=debug_mode z=instanced w=matid_vis */
};

struct MatCBData {
    float mat[4];           /* x=has_tex y=has_normal z=has_mg w=gamma */
};

struct IndexedCBData {
    float offset_scale[196][4];
    float rotation[196][4];
    float tile_idx[196][4];
    float tint[196][4];
    float remove[196][4];
};

} /* namespace */

struct wsr_renderer {
    HWND     hwnd      = nullptr;
    uint32_t width     = 1;      /* 逻辑尺寸 */
    uint32_t height    = 1;      /* 逻辑尺寸 */
    float    dpi_scale = 1.0f;
    uint32_t flags     = WSR_FLAG_NONE;

    ComPtr<ID3D11Device>           device;
    ComPtr<ID3D11DeviceContext>    ctx;
    ComPtr<IDXGISwapChain1>        swapchain;
    ComPtr<ID3D11RenderTargetView> rtv;
    ComPtr<ID3D11Texture2D>        depth_tex;
    ComPtr<ID3D11DepthStencilView> dsv;

    /* 着色器（PBS / wire / unlit / INDEXED 共用一个 PS，靠 mode 分支区分，
     * 与 GLSL 的 u_mode 一一对应，便于逐项核对） */
    ComPtr<ID3D11VertexShader> vs;
    ComPtr<ID3D11PixelShader>  ps;
    ComPtr<ID3D11PixelShader>  ps_mrt;      /* Pass1：未打光 albedo + 世界法线 + 世界坐标 */
    ComPtr<ID3D11VertexShader> vs_fs;       /* 全屏三角形（SV_VertexID） */
    ComPtr<ID3D11PixelShader>  ps_fs;       /* 拷贝法线 / 最终光照 / debug 通道 */

    /* deferred 中间缓冲（随尺寸重建） */
    ComPtr<ID3D11Texture2D> scene_albedo_tex, scene_normal_tex, scene_world_tex;
    ComPtr<ID3D11RenderTargetView> scene_albedo_rtv, scene_normal_rtv, scene_world_rtv;
    ComPtr<ID3D11ShaderResourceView> scene_albedo_srv, scene_normal_srv, scene_world_srv;
    ComPtr<ID3D11Texture2D> na_tex, nb_tex;
    ComPtr<ID3D11RenderTargetView> na_rtv, nb_rtv;
    ComPtr<ID3D11ShaderResourceView> na_srv, nb_srv;
    /* 两套输入布局：单次绘制 / 实例化。
     * 不靠 shader 开关区分 ⇒ 避开旧版「实例属性始终 enabled → 单次绘制被二次变换」的坑。 */
    ComPtr<ID3D11InputLayout>  layout;
    ComPtr<ID3D11InputLayout>  layout_inst;

    ComPtr<ID3D11Buffer> cb_frame;    /* b0 */
    ComPtr<ID3D11Buffer> cb_mat;      /* b1 */
    ComPtr<ID3D11Buffer> cb_indexed;  /* b2 */

    ComPtr<ID3D11RasterizerState>   rs_solid;
    ComPtr<ID3D11RasterizerState>   rs_bias1;   /* 装甲平涂：z-fight 偏移 */
    ComPtr<ID3D11RasterizerState>   rs_bias2;   /* 边界线 / 高亮：更强偏移 */
    ComPtr<ID3D11DepthStencilState> dss_default;   /* 写深度 */
    ComPtr<ID3D11DepthStencilState> dss_no_write;  /* 不写深度（LEQUAL） */
    ComPtr<ID3D11BlendState>        bs_opaque;
    ComPtr<ID3D11BlendState>        bs_alpha;
    ComPtr<ID3D11SamplerState>      smp_linear;      /* wrap + mip 线性 */
    ComPtr<ID3D11SamplerState>      smp_point;       /* clamp + point（materialIdMap） */
    ComPtr<ID3D11SamplerState>      smp_wrap_point;  /* wrap + point */

    std::unordered_map<std::string, TextureRes> textures;
    std::vector<MeshRes> meshes;
    std::unordered_map<std::string, size_t> mesh_index;

    bool             frame_valid = false;
    wsr_frame_params frame = {};
    FrameCBData      fs_template = {};   /* 全屏 pass 的常量模板（光照参数） */
    wsr_view_options view = {};

    /* 天空背景色（与旧版 glClearColor(0.30, 0.46, 0.60, 1.0) 一致） */
    float clear_color[4] = { 0.30f, 0.46f, 0.60f, 1.0f };

    uint32_t draw_calls        = 0;
    uint32_t device_lost_count = 0;
    uint32_t frame_index       = 0;
    /* 重复 mesh key 被就地替换的次数（>0 = Python 侧 key 不唯一 ⇒ 网格静默丢失） */
    uint32_t dup_mesh_keys     = 0;
    double   frame_ms_last     = 0.0;
    double   frame_ms_avg      = 0.0;
    bool     simulate_lost     = false;
    /* 设备丢失重建后置位：Python 侧检测到后重新提交场景/纹理（CPU 侧描述为权威副本） */
    bool     need_resubmit     = true;
    LARGE_INTEGER qpc_freq{};
    LARGE_INTEGER qpc_last{};
};

namespace {

/* ---------- 尺寸换算 ---------- */
uint32_t pixel_width(const wsr_renderer *r)
{
    const float s = (r->dpi_scale > 0.0f) ? r->dpi_scale : 1.0f;
    const uint32_t v = static_cast<uint32_t>(static_cast<float>(r->width) * s + 0.5f);
    return v ? v : 1u;
}

uint32_t pixel_height(const wsr_renderer *r)
{
    const float s = (r->dpi_scale > 0.0f) ? r->dpi_scale : 1.0f;
    const uint32_t v = static_cast<uint32_t>(static_cast<float>(r->height) * s + 0.5f);
    return v ? v : 1u;
}

/* ---------- GPU 资源释放（重建的第一步） ---------- */
void release_gpu(wsr_renderer *r)
{
    if (r->ctx) {
        r->ctx->ClearState();
        r->ctx->Flush();
    }

    /* 场景/纹理的 CPU 侧描述由调用方（Python）持有，这里只丢弃 GPU 副本。 */
    r->textures.clear();
    r->meshes.clear();
    r->mesh_index.clear();
    r->dup_mesh_keys = 0;

    r->nb_srv.Reset();
    r->na_srv.Reset();
    r->nb_rtv.Reset();
    r->na_rtv.Reset();
    r->nb_tex.Reset();
    r->na_tex.Reset();
    r->scene_world_srv.Reset();
    r->scene_normal_srv.Reset();
    r->scene_albedo_srv.Reset();
    r->scene_world_rtv.Reset();
    r->scene_normal_rtv.Reset();
    r->scene_albedo_rtv.Reset();
    r->scene_world_tex.Reset();
    r->scene_normal_tex.Reset();
    r->scene_albedo_tex.Reset();
    r->ps_fs.Reset();
    r->vs_fs.Reset();
    r->ps_mrt.Reset();

    r->smp_wrap_point.Reset();
    r->smp_point.Reset();
    r->smp_linear.Reset();
    r->bs_alpha.Reset();
    r->bs_opaque.Reset();
    r->dss_no_write.Reset();
    r->dss_default.Reset();
    r->rs_bias2.Reset();
    r->rs_bias1.Reset();
    r->rs_solid.Reset();
    r->cb_indexed.Reset();
    r->cb_mat.Reset();
    r->cb_frame.Reset();
    r->layout_inst.Reset();
    r->layout.Reset();
    r->ps.Reset();
    r->vs.Reset();
    r->dsv.Reset();
    r->depth_tex.Reset();
    r->rtv.Reset();
    r->swapchain.Reset();
    r->ctx.Reset();
    r->device.Reset();
}

/* ---------- Device ---------- */
HRESULT create_device(wsr_renderer *r)
{
    const UINT create_flags = 0; /* 不启用 DEBUG 层：发布/调试统一行为 */
    D3D_FEATURE_LEVEL levels[] = { D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0 };
    D3D_FEATURE_LEVEL got = D3D_FEATURE_LEVEL_11_0;

    HRESULT hr = ::D3D11CreateDevice(
        nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, create_flags,
        levels, _countof(levels), D3D11_SDK_VERSION,
        r->device.ReleaseAndGetAddressOf(), &got, r->ctx.ReleaseAndGetAddressOf());

    /* 旧系统不识别 11_1 → 回退仅请求 11_0 */
    if (hr == E_INVALIDARG) {
        D3D_FEATURE_LEVEL fallback[] = { D3D_FEATURE_LEVEL_11_0 };
        hr = ::D3D11CreateDevice(
            nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, create_flags,
            fallback, 1, D3D11_SDK_VERSION,
            r->device.ReleaseAndGetAddressOf(), &got, r->ctx.ReleaseAndGetAddressOf());
    }
    return hr;
}

/* ---------- SwapChain ---------- */
HRESULT create_swapchain(wsr_renderer *r)
{
    ComPtr<IDXGIDevice> dxgi_device;
    HRESULT hr = r->device.As(&dxgi_device);
    if (FAILED(hr)) {
        return hr;
    }

    ComPtr<IDXGIAdapter> adapter;
    hr = dxgi_device->GetAdapter(adapter.ReleaseAndGetAddressOf());
    if (FAILED(hr)) {
        return hr;
    }

    ComPtr<IDXGIFactory2> factory;
    hr = adapter->GetParent(IID_PPV_ARGS(factory.ReleaseAndGetAddressOf()));
    if (FAILED(hr)) {
        return hr;
    }

    DXGI_SWAP_CHAIN_DESC1 sd = {};
    sd.Width       = pixel_width(r);
    sd.Height      = pixel_height(r);
    sd.Format      = DXGI_FORMAT_B8G8R8A8_UNORM;
    sd.Stereo      = FALSE;
    sd.SampleDesc.Count   = 1;
    sd.SampleDesc.Quality = 0;
    sd.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    sd.BufferCount = 2;
    sd.Scaling     = DXGI_SCALING_STRETCH;
    sd.SwapEffect  = (r->flags & WSR_FLAG_LEGACY_BITBLT)
                         ? DXGI_SWAP_EFFECT_DISCARD
                         : DXGI_SWAP_EFFECT_FLIP_DISCARD;
    sd.AlphaMode   = DXGI_ALPHA_MODE_IGNORE;
    sd.Flags       = 0;

    return factory->CreateSwapChainForHwnd(
        r->device.Get(), r->hwnd, &sd, nullptr, nullptr,
        r->swapchain.ReleaseAndGetAddressOf());
}

HRESULT create_screen_targets(wsr_renderer *r);
HRESULT create_render_target(wsr_renderer *r)
{
    ComPtr<ID3D11Texture2D> backbuffer;
    HRESULT hr = r->swapchain->GetBuffer(0, IID_PPV_ARGS(backbuffer.ReleaseAndGetAddressOf()));
    if (FAILED(hr)) {
        return hr;
    }
    hr = r->device->CreateRenderTargetView(
        backbuffer.Get(), nullptr, r->rtv.ReleaseAndGetAddressOf());
    if (FAILED(hr)) {
        return hr;
    }

    /* 深度缓冲（D24S8）。几何/装甲/透明 pass 均依赖它；deferred 的深度也复用同一张
     * （Pass1 写入后保留，后续透明/装甲直接测试，无需旧版的深度 blit）。 */
    D3D11_TEXTURE2D_DESC dd = {};
    dd.Width            = pixel_width(r);
    dd.Height           = pixel_height(r);
    dd.MipLevels        = 1;
    dd.ArraySize        = 1;
    dd.Format           = DXGI_FORMAT_D24_UNORM_S8_UINT;
    dd.SampleDesc.Count = 1;
    dd.Usage            = D3D11_USAGE_DEFAULT;
    dd.BindFlags        = D3D11_BIND_DEPTH_STENCIL;
    hr = r->device->CreateTexture2D(&dd, nullptr, r->depth_tex.ReleaseAndGetAddressOf());
    if (FAILED(hr)) {
        return hr;
    }
    hr = r->device->CreateDepthStencilView(
        r->depth_tex.Get(), nullptr, r->dsv.ReleaseAndGetAddressOf());
    if (FAILED(hr)) {
        return hr;
    }

    return create_screen_targets(r);
}

/* ---------- deferred 中间缓冲（随尺寸重建） ---------- */
HRESULT create_screen_targets(wsr_renderer *r)
{
    D3D11_TEXTURE2D_DESC td = {};
    td.Width            = pixel_width(r);
    td.Height           = pixel_height(r);
    td.MipLevels        = 1;
    td.ArraySize        = 1;
    td.SampleDesc.Count = 1;
    td.Usage            = D3D11_USAGE_DEFAULT;
    td.BindFlags        = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;

    const auto make = [&](DXGI_FORMAT fmt, ComPtr<ID3D11Texture2D> &tex,
                          ComPtr<ID3D11RenderTargetView> &rtv,
                          ComPtr<ID3D11ShaderResourceView> &srv) -> HRESULT {
        tex.Reset();
        rtv.Reset();
        srv.Reset();
        td.Format = fmt;
        HRESULT hr2 = r->device->CreateTexture2D(&td, nullptr, tex.ReleaseAndGetAddressOf());
        if (FAILED(hr2)) {
            return hr2;
        }
        hr2 = r->device->CreateRenderTargetView(tex.Get(), nullptr, rtv.ReleaseAndGetAddressOf());
        if (FAILED(hr2)) {
            return hr2;
        }
        return r->device->CreateShaderResourceView(tex.Get(), nullptr, srv.ReleaseAndGetAddressOf());
    };

    /* Pass1 三附件：未打光 albedo / 世界法线 / 世界坐标（与旧版 MRT 格式对应） */
    HRESULT hr = make(DXGI_FORMAT_R8G8B8A8_UNORM, r->scene_albedo_tex,
                      r->scene_albedo_rtv, r->scene_albedo_srv);
    if (FAILED(hr)) {
        return hr;
    }
    hr = make(DXGI_FORMAT_R8G8B8A8_UNORM, r->scene_normal_tex,
              r->scene_normal_rtv, r->scene_normal_srv);
    if (FAILED(hr)) {
        return hr;
    }
    hr = make(DXGI_FORMAT_R32G32B32A32_FLOAT, r->scene_world_tex,
              r->scene_world_rtv, r->scene_world_srv);
    if (FAILED(hr)) {
        return hr;
    }
    /* na / nb：法线累积缓冲（Hull → na；nb = Hull 打底 + decal 合成） */
    hr = make(DXGI_FORMAT_R8G8B8A8_UNORM, r->na_tex, r->na_rtv, r->na_srv);
    if (FAILED(hr)) {
        return hr;
    }
    return make(DXGI_FORMAT_R8G8B8A8_UNORM, r->nb_tex, r->nb_rtv, r->nb_srv);
}

/* ---------- 管线资源 ---------- */
static const D3D11_INPUT_ELEMENT_DESC kElemsBase[] = {
    { "POSITION", 0, DXGI_FORMAT_R32G32B32_FLOAT,    0,  0, D3D11_INPUT_PER_VERTEX_DATA, 0 },
    { "NORMAL",   0, DXGI_FORMAT_R32G32B32_FLOAT,    0, 12, D3D11_INPUT_PER_VERTEX_DATA, 0 },
    { "TEXCOORD", 0, DXGI_FORMAT_R32G32_FLOAT,       0, 24, D3D11_INPUT_PER_VERTEX_DATA, 0 },
    { "COLOR",    0, DXGI_FORMAT_R32G32B32A32_FLOAT, 0, 32, D3D11_INPUT_PER_VERTEX_DATA, 0 },
};

static const D3D11_INPUT_ELEMENT_DESC kElemsInst[] = {
    { "POSITION", 0, DXGI_FORMAT_R32G32B32_FLOAT,    0,  0, D3D11_INPUT_PER_VERTEX_DATA, 0 },
    { "NORMAL",   0, DXGI_FORMAT_R32G32B32_FLOAT,    0, 12, D3D11_INPUT_PER_VERTEX_DATA, 0 },
    { "TEXCOORD", 0, DXGI_FORMAT_R32G32_FLOAT,       0, 24, D3D11_INPUT_PER_VERTEX_DATA, 0 },
    { "COLOR",    0, DXGI_FORMAT_R32G32B32A32_FLOAT, 0, 32, D3D11_INPUT_PER_VERTEX_DATA, 0 },
    { "INST",     0, DXGI_FORMAT_R32G32B32A32_FLOAT, 1,  0, D3D11_INPUT_PER_INSTANCE_DATA, 1 },
    { "INST",     1, DXGI_FORMAT_R32G32B32A32_FLOAT, 1, 16, D3D11_INPUT_PER_INSTANCE_DATA, 1 },
    { "INST",     2, DXGI_FORMAT_R32G32B32A32_FLOAT, 1, 32, D3D11_INPUT_PER_INSTANCE_DATA, 1 },
    { "INST",     3, DXGI_FORMAT_R32G32B32A32_FLOAT, 1, 48, D3D11_INPUT_PER_INSTANCE_DATA, 1 },
};

HRESULT create_pipeline(wsr_renderer *r)
{
    HRESULT hr = r->device->CreateVertexShader(
        g_material_vs_bytes, sizeof(g_material_vs_bytes), nullptr,
        r->vs.ReleaseAndGetAddressOf());
    if (FAILED(hr)) {
        set_error("pipeline: CreateVertexShader (hr=0x%08X)", static_cast<unsigned>(hr));
        return hr;
    }
    hr = r->device->CreatePixelShader(
        g_material_ps_bytes, sizeof(g_material_ps_bytes), nullptr,
        r->ps.ReleaseAndGetAddressOf());
    if (FAILED(hr)) {
        set_error("pipeline: CreatePixelShader (hr=0x%08X)", static_cast<unsigned>(hr));
        return hr;
    }
    hr = r->device->CreatePixelShader(
        g_material_ps_mrt_bytes, sizeof(g_material_ps_mrt_bytes), nullptr,
        r->ps_mrt.ReleaseAndGetAddressOf());
    if (FAILED(hr)) {
        set_error("pipeline: CreatePixelShader(mrt) (hr=0x%08X)", static_cast<unsigned>(hr));
        return hr;
    }
    hr = r->device->CreateVertexShader(
        g_fullscreen_vs_bytes, sizeof(g_fullscreen_vs_bytes), nullptr,
        r->vs_fs.ReleaseAndGetAddressOf());
    if (FAILED(hr)) {
        set_error("pipeline: CreateVertexShader(fs) (hr=0x%08X)", static_cast<unsigned>(hr));
        return hr;
    }
    hr = r->device->CreatePixelShader(
        g_fullscreen_ps_bytes, sizeof(g_fullscreen_ps_bytes), nullptr,
        r->ps_fs.ReleaseAndGetAddressOf());
    if (FAILED(hr)) {
        set_error("pipeline: CreatePixelShader(fs) (hr=0x%08X)", static_cast<unsigned>(hr));
        return hr;
    }
    /* 单套完整输入布局（含实例语义）：单次绘制把 model_matrix 也当作 1 个实例提交，
     * 既避开「布局缺 INST 元素导致 CreateInputLayout 失败」，也避开旧版
     * 「实例属性始终 enabled → 单次绘制被二次变换」的历史坑。 */
    hr = r->device->CreateInputLayout(
        kElemsInst, _countof(kElemsInst), g_material_vs_bytes, sizeof(g_material_vs_bytes),
        r->layout.ReleaseAndGetAddressOf());
    if (FAILED(hr)) {
        set_error("pipeline: CreateInputLayout (hr=0x%08X)", static_cast<unsigned>(hr));
        return hr;
    }

    /* 常量缓冲 */
    D3D11_BUFFER_DESC cbd = {};
    cbd.Usage          = D3D11_USAGE_DYNAMIC;
    cbd.BindFlags      = D3D11_BIND_CONSTANT_BUFFER;
    cbd.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;

    cbd.ByteWidth = (UINT)sizeof(FrameCBData);
    hr = r->device->CreateBuffer(&cbd, nullptr, r->cb_frame.ReleaseAndGetAddressOf());
    if (FAILED(hr)) {
        set_error("pipeline: cb_frame size=%u (hr=0x%08X)",
                  static_cast<unsigned>(cbd.ByteWidth), static_cast<unsigned>(hr));
        return hr;
    }

    cbd.ByteWidth = (UINT)sizeof(MatCBData);
    hr = r->device->CreateBuffer(&cbd, nullptr, r->cb_mat.ReleaseAndGetAddressOf());
    if (FAILED(hr)) {
        set_error("pipeline: cb_mat size=%u (hr=0x%08X)",
                  static_cast<unsigned>(cbd.ByteWidth), static_cast<unsigned>(hr));
        return hr;
    }

    cbd.ByteWidth = (UINT)sizeof(IndexedCBData);
    hr = r->device->CreateBuffer(&cbd, nullptr, r->cb_indexed.ReleaseAndGetAddressOf());
    if (FAILED(hr)) {
        set_error("pipeline: cb_indexed size=%u (hr=0x%08X)",
                  static_cast<unsigned>(cbd.ByteWidth), static_cast<unsigned>(hr));
        return hr;
    }

    /* 光栅化状态：旧版不启用面剔除（双面渲染）⇒ CULL_NONE */
    D3D11_RASTERIZER_DESC rd = {};
    rd.FillMode        = D3D11_FILL_SOLID;
    rd.CullMode        = D3D11_CULL_NONE;
    rd.DepthClipEnable = TRUE;
    hr = r->device->CreateRasterizerState(&rd, r->rs_solid.ReleaseAndGetAddressOf());
    if (FAILED(hr)) return hr;

    D3D11_RASTERIZER_DESC rb1 = rd;
    rb1.SlopeScaledDepthBias = -1.0f;
    rb1.DepthBias            = -2;
    hr = r->device->CreateRasterizerState(&rb1, r->rs_bias1.ReleaseAndGetAddressOf());
    if (FAILED(hr)) return hr;

    D3D11_RASTERIZER_DESC rb2 = rd;
    rb2.SlopeScaledDepthBias = -2.0f;
    rb2.DepthBias            = -4;
    hr = r->device->CreateRasterizerState(&rb2, r->rs_bias2.ReleaseAndGetAddressOf());
    if (FAILED(hr)) return hr;

    /* 深度模板状态 */
    D3D11_DEPTH_STENCIL_DESC ds = {};
    ds.DepthEnable    = TRUE;
    ds.DepthWriteMask = D3D11_DEPTH_WRITE_MASK_ALL;
    ds.DepthFunc      = D3D11_COMPARISON_LESS_EQUAL;
    hr = r->device->CreateDepthStencilState(&ds, r->dss_default.ReleaseAndGetAddressOf());
    if (FAILED(hr)) return hr;

    ds.DepthWriteMask = D3D11_DEPTH_WRITE_MASK_ZERO;
    hr = r->device->CreateDepthStencilState(&ds, r->dss_no_write.ReleaseAndGetAddressOf());
    if (FAILED(hr)) return hr;

    /* 混合状态（⚠️ RenderTargetWriteMask 需逐个附件设置：默认 RT1..7 写掩码为 0，
     * 会让 MRT 的第 2/3 个附件永远拿不到数据。） */
    D3D11_BLEND_DESC bd = {};
    for (int i = 0; i < 8; ++i) {
        bd.RenderTarget[i].RenderTargetWriteMask = D3D11_COLOR_WRITE_ENABLE_ALL;
    }
    bd.RenderTarget[0].BlendEnable = FALSE;
    hr = r->device->CreateBlendState(&bd, r->bs_opaque.ReleaseAndGetAddressOf());
    if (FAILED(hr)) return hr;

    bd.RenderTarget[0].BlendEnable           = TRUE;
    bd.RenderTarget[0].SrcBlend              = D3D11_BLEND_SRC_ALPHA;
    bd.RenderTarget[0].DestBlend             = D3D11_BLEND_INV_SRC_ALPHA;
    bd.RenderTarget[0].BlendOp               = D3D11_BLEND_OP_ADD;
    bd.RenderTarget[0].SrcBlendAlpha         = D3D11_BLEND_ONE;
    bd.RenderTarget[0].DestBlendAlpha        = D3D11_BLEND_INV_SRC_ALPHA;
    bd.RenderTarget[0].BlendOpAlpha          = D3D11_BLEND_OP_ADD;
    hr = r->device->CreateBlendState(&bd, r->bs_alpha.ReleaseAndGetAddressOf());
    if (FAILED(hr)) return hr;

    /* 采样器 */
    D3D11_SAMPLER_DESC sd = {};
    sd.AddressU = sd.AddressV = sd.AddressW = D3D11_TEXTURE_ADDRESS_WRAP;
    sd.Filter   = D3D11_FILTER_MIN_MAG_MIP_LINEAR;
    sd.MaxLOD   = D3D11_FLOAT32_MAX;
    hr = r->device->CreateSamplerState(&sd, r->smp_linear.ReleaseAndGetAddressOf());
    if (FAILED(hr)) return hr;

    sd.AddressU = sd.AddressV = sd.AddressW = D3D11_TEXTURE_ADDRESS_CLAMP;
    sd.Filter   = D3D11_FILTER_MIN_MAG_MIP_POINT;
    hr = r->device->CreateSamplerState(&sd, r->smp_point.ReleaseAndGetAddressOf());
    if (FAILED(hr)) return hr;

    sd.AddressU = sd.AddressV = sd.AddressW = D3D11_TEXTURE_ADDRESS_WRAP;
    sd.Filter   = D3D11_FILTER_MIN_MAG_MIP_POINT;
    hr = r->device->CreateSamplerState(&sd, r->smp_wrap_point.ReleaseAndGetAddressOf());
    if (FAILED(hr)) return hr;

    return S_OK;
}

/* ---------- 设备丢失最小重建链路 ---------- */
bool rebuild(wsr_renderer *r)
{
    release_gpu(r);
    g_last_error.clear();

    HRESULT hr = create_device(r);
    if (FAILED(hr)) {
        if (g_last_error.empty()) {
            set_error("create_device failed (hr=0x%08X)", static_cast<unsigned>(hr));
        }
        return false;
    }
    hr = create_swapchain(r);
    if (FAILED(hr)) {
        if (g_last_error.empty()) {
            set_error("create_swapchain failed (hr=0x%08X)", static_cast<unsigned>(hr));
        }
        return false;
    }
    hr = create_render_target(r);
    if (FAILED(hr)) {
        if (g_last_error.empty()) {
            set_error("create_render_target failed (hr=0x%08X)", static_cast<unsigned>(hr));
        }
        return false;
    }
    hr = create_pipeline(r);
    if (FAILED(hr)) {
        if (g_last_error.empty()) {
            set_error("create_pipeline failed (hr=0x%08X)", static_cast<unsigned>(hr));
        }
        return false;
    }

    /* GPU 副本已重建但内容为空：请调用方重新提交场景/纹理 */
    r->need_resubmit = true;
    QueryPerformanceFrequency(&r->qpc_freq);
    QueryPerformanceCounter(&r->qpc_last);
    return true;
}

bool is_device_lost(HRESULT hr)
{
    return hr == DXGI_ERROR_DEVICE_REMOVED || hr == DXGI_ERROR_DEVICE_RESET;
}

void sample_frame_time(wsr_renderer *r)
{
    if (r->qpc_freq.QuadPart == 0) {
        return;
    }
    LARGE_INTEGER now;
    QueryPerformanceCounter(&now);
    if (r->qpc_last.QuadPart != 0) {
        const double ms =
            static_cast<double>(now.QuadPart - r->qpc_last.QuadPart) * 1000.0 /
            static_cast<double>(r->qpc_freq.QuadPart);
        r->frame_ms_last = ms;
        r->frame_ms_avg = (r->frame_ms_avg <= 0.0) ? ms : (r->frame_ms_avg * 0.9 + ms * 0.1);
    }
    r->qpc_last = now;
}

/* ---------- 矩阵工具（行主序，out = a * b） ---------- */
void mat4_mul(const float *a, const float *b, float *out)
{
    for (int i = 0; i < 4; ++i) {
        for (int j = 0; j < 4; ++j) {
            out[i * 4 + j] = a[i * 4 + 0] * b[0 * 4 + j]
                           + a[i * 4 + 1] * b[1 * 4 + j]
                           + a[i * 4 + 2] * b[2 * 4 + j]
                           + a[i * 4 + 3] * b[3 * 4 + j];
        }
    }
}

const float kIdentity4[16] = { 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1 };

bool map_write(wsr_renderer *r, ID3D11Buffer *cb, const void *data, size_t size)
{
    D3D11_MAPPED_SUBRESOURCE ms = {};
    if (FAILED(r->ctx->Map(cb, 0, D3D11_MAP_WRITE_DISCARD, 0, &ms))) {
        return false;
    }
    memcpy(ms.pData, data, size);
    r->ctx->Unmap(cb, 0);
    return true;
}

/* 绑定该 mesh 声明的纹理（未声明的槽显式置空，避免残留上一 mesh 的绑定）。 */
void bind_textures(wsr_renderer *r, const MaterialRes &mat, ID3D11ShaderResourceView **out_srvs)
{
    for (int i = 0; i < WSR_TEX_COUNT; ++i) {
        out_srvs[i] = nullptr;
        const std::string &key = mat.tex[i];
        if (key.empty()) {
            continue;
        }
        auto it = r->textures.find(key);
        if (it != r->textures.end()) {
            out_srvs[i] = it->second.srv.Get();
        }
    }
    r->ctx->PSSetShaderResources(0, WSR_TEX_COUNT, out_srvs);
}

/* 绘制单个 mesh：上传常量缓冲 + 绑定资源 + Draw。
 * mode: 0=PBS 1=线框 2=无光照 3=INDEXED；model 为 NULL 表示单位阵；
 * instanced=true 时 mvp 只含 proj*view（逐实例矩阵由 INST 属性提供）。 */
void draw_one(wsr_renderer *r, MeshRes &m, int mode, const float *model, bool instanced,
              float opacity, float emissive_on, float emissive_k, bool matid_vis,
              bool mrt_output)
{
    ID3D11DeviceContext *ctx = r->ctx.Get();
    ctx->PSSetShader(mrt_output ? r->ps_mrt.Get() : r->ps.Get(), nullptr, 0);

    FrameCBData fc = {};
    /* 统一实例化：mvp 只含 proj*view，逐实例矩阵由 INST 属性提供，
     * 法线矩阵为恒等（变换在 VS 里与实例矩阵合并）。 */
    mat4_mul(r->frame.proj, r->frame.view, fc.mvp);
    memcpy(fc.normal_mat, kIdentity4, sizeof(fc.normal_mat));

    memcpy(fc.light_dir, r->frame.light_dir, 3 * sizeof(float));
    memcpy(fc.ambient, r->frame.ambient, 3 * sizeof(float));
    memcpy(fc.light_pos, r->frame.light_pos, 3 * sizeof(float));
    /* view 矩阵第 3 行 = -forward ⇒ 正好是旧版的 (eye - target) 归一化方向 */
    fc.view_dir[0] = r->frame.view[8];
    fc.view_dir[1] = r->frame.view[9];
    fc.view_dir[2] = r->frame.view[10];

    fc.params[0] = r->frame.normal_strength;
    fc.params[1] = opacity;
    fc.params[2] = emissive_k;
    fc.params[3] = emissive_on;
    fc.params2[0] = (float)mode;
    fc.params2[1] = (float)r->frame.debug_mode;
    fc.params2[2] = 1.0f;   /* 恒为实例化路径 */
    fc.params2[3] = matid_vis ? 1.0f : 0.0f;
    map_write(r, r->cb_frame.Get(), &fc, sizeof(fc));

    /* 材质常量 */
    ID3D11ShaderResourceView *srvs[WSR_TEX_COUNT] = {};
    bind_textures(r, m.mat, srvs);

    MatCBData mc = {};
    mc.mat[0] = srvs[WSR_TEX_DIFFUSE] ? 1.0f : 0.0f;
    mc.mat[1] = srvs[WSR_TEX_NORMAL] ? 1.0f : 0.0f;
    mc.mat[2] = srvs[WSR_TEX_MG] ? 1.0f : 0.0f;
    mc.mat[3] = 2.2f;
    map_write(r, r->cb_mat.Get(), &mc, sizeof(mc));

    ID3D11Buffer *pcbs[3] = { r->cb_frame.Get(), r->cb_mat.Get(), r->cb_indexed.Get() };
    ctx->PSSetConstantBuffers(0, 3, pcbs);

    if (mode == 3) {
        IndexedCBData ic = {};
        const uint32_t n = (m.mat.matid_count < 196u) ? m.mat.matid_count : 196u;
        const auto copy_arr = [&](std::vector<float> &src, float (*dst)[4]) {
            const uint32_t avail = (uint32_t)(src.size() / 4u);
            const uint32_t cnt = (avail < n) ? avail : n;
            if (cnt) {
                memcpy(dst, src.data(), cnt * 4u * sizeof(float));
            }
        };
        copy_arr(m.mat.offset_scale, ic.offset_scale);
        copy_arr(m.mat.rotation, ic.rotation);
        copy_arr(m.mat.tile_idx, ic.tile_idx);
        copy_arr(m.mat.tint, ic.tint);
        copy_arr(m.mat.remove, ic.remove);
        map_write(r, r->cb_indexed.Get(), &ic, sizeof(ic));
    }

    ID3D11Buffer *vbs[1] = { m.vb.Get() };
    UINT stride = VERTEX_STRIDE;
    UINT offset = 0;
    ctx->IASetVertexBuffers(0, 1, vbs, &stride, &offset);
    ctx->IASetIndexBuffer(m.ib.Get(), DXGI_FORMAT_R32_UINT, 0);

    if (m.instance_count == 0) {
        return;
    }
    ID3D11Buffer *ivbs[1] = { m.inst_vb.Get() };
    UINT ist = 64;
    UINT ioff = 0;
    ctx->IASetVertexBuffers(1, 1, ivbs, &ist, &ioff);
    ctx->IASetInputLayout(r->layout.Get());
    /* 装甲板边界线等走 LINELIST（旧版对应 GL_LINES 路径） */
    const bool as_lines = (m.mat.flags & WSR_MESHF_LINES) != 0;
    ctx->IASetPrimitiveTopology(as_lines ? D3D11_PRIMITIVE_TOPOLOGY_LINELIST
                                         : D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    ctx->DrawIndexedInstanced(m.index_count, m.instance_count, 0, 0, 0);
    r->draw_calls++;
}

/* Pass1：不透明实体 → scene MRT（跳过无光照/透明/法线叠加层，与旧版 _draw_ship_solid 一致） */
void draw_solid_pass(wsr_renderer *r, bool matid_vis, bool mrt_output)
{
    for (MeshRes &m : r->meshes) {
        if (!m.visible || m.index_count == 0) continue;
        if (m.kind != WSR_MESH_HULL && m.kind != WSR_MESH_MOUNT) continue;
        if (r->view.show_armor) continue;   /* 装甲模式下不画舰体 */
        if (m.kind == WSR_MESH_HULL && !r->view.show_hull) continue;
        if (m.kind == WSR_MESH_MOUNT && !r->view.show_mounts) continue;
        const uint32_t fam = m.mat.family;
        if (fam == WSR_FAM_EMISSIVE || fam == WSR_FAM_UNLIT || fam == WSR_FAM_DECAL_NORMAL) {
            continue;
        }
        draw_one(r, m, (fam == WSR_FAM_INDEXED) ? 3 : 0, nullptr, true,
                 1.0f, 0.0f, 1.0f, matid_vis, mrt_output);   /* DIAG: 单输出 PS */
    }
}

/* 全屏三角形（SV_VertexID 生成顶点，无 VB/IB） */
void draw_fullscreen(wsr_renderer *r, int mode)
{
    FrameCBData fc = r->fs_template;
    fc.params2[0] = (float)mode;
    fc.params2[1] = (float)r->frame.debug_mode;
    fc.params2[2] = 0.0f;
    fc.params2[3] = 0.0f;
    map_write(r, r->cb_frame.Get(), &fc, sizeof(fc));
    r->ctx->Draw(3, 0);
    r->draw_calls++;
}

void bind_scene_srvs(wsr_renderer *r, ID3D11ShaderResourceView *normal_src,
                     ID3D11ShaderResourceView *final_src)
{
    ID3D11ShaderResourceView *srvs[4] = {
        r->scene_albedo_srv.Get(), normal_src, final_src, r->scene_world_srv.Get()
    };
    r->ctx->PSSetShaderResources(10, 4, srvs);
}

void unbind_scene_srvs(wsr_renderer *r)
{
    ID3D11ShaderResourceView *nulls[4] = { nullptr, nullptr, nullptr, nullptr };
    r->ctx->PSSetShaderResources(10, 4, nulls);
}

} /* namespace */

/* ============================ C ABI ============================ */

extern "C" {

int32_t wsr_create(void *hwnd, uint32_t width, uint32_t height,
                   uint32_t flags, wsr_renderer **out)
{
    if (out == nullptr) {
        return fail(WSR_ERR_INVALID_ARG, "wsr_create: out is null");
    }
    *out = nullptr;

    if (hwnd == nullptr) {
        return fail(WSR_ERR_INVALID_ARG, "wsr_create: hwnd is null");
    }

    wsr_renderer *r = new (std::nothrow) wsr_renderer();
    if (r == nullptr) {
        return fail(WSR_ERR_OUT_OF_MEMORY, "wsr_create: allocation failed");
    }

    r->hwnd   = static_cast<HWND>(hwnd);
    r->width  = width  ? width  : 1u;
    r->height = height ? height : 1u;
    r->flags  = flags;

    /* 视图选项默认值（与旧版查看器的初始状态一致） */
    r->view.struct_size    = sizeof(wsr_view_options);
    r->view.show_hull      = 1;
    r->view.show_mounts    = 1;
    r->view.show_armor     = 0;
    r->view.wireframe      = 0;
    r->view.show_edges     = 1;
    r->view.armor_opacity  = 0.45f;

    if (!rebuild(r)) {
        const std::string why = g_last_error;
        delete r;
        return fail(WSR_ERR_DEVICE, "wsr_create: %s", why.c_str());
    }

    *out = r;
    return WSR_OK;
}

void wsr_destroy(wsr_renderer *r)
{
    if (r == nullptr) {
        return;
    }
    release_gpu(r);
    delete r;
}

int32_t wsr_resize(wsr_renderer *r, uint32_t width, uint32_t height)
{
    if (r == nullptr) {
        return fail(WSR_ERR_INVALID_ARG, "wsr_resize: renderer is null");
    }

    const uint32_t w = width  ? width  : 1u;
    const uint32_t h = height ? height : 1u;
    if (w == r->width && h == r->height) {
        return WSR_OK;
    }
    r->width  = w;
    r->height = h;

    if (!r->swapchain) {
        return WSR_OK; /* 尚未建立交换链，尺寸记录即可 */
    }

    r->rtv.Reset();
    if (r->ctx) {
        r->ctx->OMSetRenderTargets(0, nullptr, nullptr);
    }

    HRESULT hr = r->swapchain->ResizeBuffers(
        0, pixel_width(r), pixel_height(r), DXGI_FORMAT_UNKNOWN, 0);

    if (is_device_lost(hr)) {
        r->device_lost_count++;
        if (!rebuild(r)) {
            const std::string why = g_last_error;
            return fail(WSR_ERR_DEVICE, "wsr_resize: rebuild failed: %s", why.c_str());
        }
        return WSR_OK;
    }
    if (FAILED(hr)) {
        return fail(WSR_ERR_SWAPCHAIN,
                    "wsr_resize: ResizeBuffers failed (hr=0x%08X)", static_cast<unsigned>(hr));
    }

    hr = create_render_target(r);
    if (FAILED(hr)) {
        return fail(WSR_ERR_SWAPCHAIN,
                    "wsr_resize: create RTV failed (hr=0x%08X)", static_cast<unsigned>(hr));
    }
    return WSR_OK;
}

int32_t wsr_set_dpi_scale(wsr_renderer *r, float scale)
{
    if (r == nullptr) {
        return fail(WSR_ERR_INVALID_ARG, "wsr_set_dpi_scale: renderer is null");
    }
    const float s = (scale > 0.0f) ? scale : 1.0f;
    if (s == r->dpi_scale) {
        return WSR_OK;
    }
    r->dpi_scale = s;
    return wsr_resize(r, r->width, r->height); /* 后备缓冲需按新缩放重建 */
}

int32_t wsr_set_options(wsr_renderer *r, const wsr_options *opt)
{
    if (r == nullptr || opt == nullptr) {
        return fail(WSR_ERR_INVALID_ARG, "wsr_set_options: null argument");
    }
    for (int i = 0; i < 4; ++i) {
        r->clear_color[i] = opt->clear_color[i];
    }
    return WSR_OK;
}

int32_t wsr_render(wsr_renderer *r)
{
    if (r == nullptr) {
        return fail(WSR_ERR_INVALID_ARG, "wsr_render: renderer is null");
    }
    if (!r->device || !r->swapchain || !r->rtv || !r->dsv) {
        return fail(WSR_ERR_DEVICE, "wsr_render: device not ready");
    }

    /* 调试：模拟设备丢失 */
    if (r->simulate_lost) {
        r->simulate_lost = false;
        r->device_lost_count++;
        if (!rebuild(r)) {
            const std::string why = g_last_error;
            return fail(WSR_ERR_DEVICE, "wsr_render: rebuild after simulated loss failed: %s",
                        why.c_str());
        }
        return WSR_OK; /* 待调用方重新提交场景 */
    }

    if (!r->frame_valid) {
        return fail(WSR_ERR_INVALID_ARG, "wsr_render: frame params not set (call wsr_frame_set)");
    }

    ID3D11DeviceContext *ctx = r->ctx.Get();
    const float vw = static_cast<float>(pixel_width(r));
    const float vh = static_cast<float>(pixel_height(r));

    /* 解绑上一帧残留的 deferred 纹理（避免同时作为 RTV/SRV） */
    unbind_scene_srvs(r);

    D3D11_VIEWPORT vp = {};
    vp.Width    = vw;
    vp.Height   = vh;
    vp.MinDepth = 0.0f;
    vp.MaxDepth = 1.0f;
    ctx->RSSetViewports(1, &vp);

    const float blend_factor[4] = { 0.0f, 0.0f, 0.0f, 0.0f };
    ctx->RSSetState(r->rs_solid.Get());
    ctx->OMSetDepthStencilState(r->dss_default.Get(), 0);
    ctx->OMSetBlendState(r->bs_opaque.Get(), blend_factor, 0xFFFFFFFF);

    ID3D11Buffer *frame_cb = r->cb_frame.Get();
    ctx->VSSetConstantBuffers(0, 1, &frame_cb);
    ctx->PSSetConstantBuffers(0, 1, &frame_cb);

    ID3D11SamplerState *smps[3] = {
        r->smp_linear.Get(), r->smp_point.Get(), r->smp_wrap_point.Get()
    };
    ctx->PSSetSamplers(0, 3, smps);

    const bool armor_mode = (r->view.show_armor != 0);
    const bool matid_vis  = (r->frame.debug_mode == 6);

    ID3D11RenderTargetView *mrt[3] = {
        r->scene_albedo_rtv.Get(), r->scene_normal_rtv.Get(), r->scene_world_rtv.Get()
    };
    if (mrt[0] == nullptr || mrt[1] == nullptr || mrt[2] == nullptr ||
        r->na_rtv == nullptr || r->nb_rtv == nullptr) {
        return fail(WSR_ERR_DEVICE, "wsr_render: deferred targets not ready");
    }

    /* ---- Pass1：不透明实体（deferred 开关决定目标）---- */
    const bool use_deferred = (r->flags & WSR_FLAG_DEFERRED) != 0;
    if (use_deferred) {
        ctx->OMSetRenderTargets(3, mrt, r->dsv.Get());
        for (int i = 0; i < 3; ++i) {
            ctx->ClearRenderTargetView(mrt[i], r->clear_color);
        }
    } else {
        ID3D11RenderTargetView *bb1[1] = { r->rtv.Get() };
        ctx->OMSetRenderTargets(1, bb1, r->dsv.Get());
        ctx->ClearRenderTargetView(r->rtv.Get(), r->clear_color);
    }
    ctx->ClearDepthStencilView(r->dsv.Get(), D3D11_CLEAR_DEPTH | D3D11_CLEAR_STENCIL, 1.0f, 0);
    ctx->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    ctx->VSSetShader(r->vs.Get(), nullptr, 0);
    draw_solid_pass(r, matid_vis, use_deferred);

    /* ---- PassA/PassB：法线累积 + Normal Detail（decal）合成 ---- */
    if (use_deferred) {
        /* PassA：Hull 世界法线 → na */
        {
            ID3D11RenderTargetView *dst = r->na_rtv.Get();
            ctx->OMSetRenderTargets(1, &dst, nullptr);
            ctx->VSSetShader(r->vs_fs.Get(), nullptr, 0);
            ctx->PSSetShader(r->ps_fs.Get(), nullptr, 0);
            ctx->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
            bind_scene_srvs(r, r->scene_normal_srv.Get(), nullptr);
            draw_fullscreen(r, 10);
        }
        /* PassB：na → nb 打底（全屏拷贝避免虚影），再叠加 decal 法线 */
        {
            ID3D11RenderTargetView *dst = r->nb_rtv.Get();
            ctx->OMSetRenderTargets(1, &dst, nullptr);
            bind_scene_srvs(r, r->na_srv.Get(), nullptr);
            draw_fullscreen(r, 10);

            bool has_decal = false;
            for (MeshRes &m : r->meshes) {
                if (m.visible && m.index_count != 0 && m.mat.family == WSR_FAM_DECAL_NORMAL) {
                    has_decal = true;
                    break;
                }
            }
            if (has_decal && !armor_mode) {
                /* ⚠️ decal 是实体几何 ⇒ 必须用实体 VS（不是全屏变体）；
                 * 深度来自 Pass1（不写深度 + LEQUAL，与旧版 PassB 一致）。*/ 
                bind_scene_srvs(r, r->na_srv.Get(), nullptr);
                ctx->OMSetRenderTargets(1, &dst, r->dsv.Get());
                ctx->VSSetShader(r->vs.Get(), nullptr, 0);
                ctx->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
                ctx->OMSetDepthStencilState(r->dss_no_write.Get(), 0);
                for (MeshRes &m : r->meshes) {
                    if (!m.visible || m.index_count == 0) continue;
                    if (m.mat.family != WSR_FAM_DECAL_NORMAL) continue;
                    if (m.kind == WSR_MESH_HULL && !r->view.show_hull) continue;
                    if (m.kind == WSR_MESH_MOUNT && !r->view.show_mounts) continue;
                    draw_one(r, m, 9, nullptr, true, 1.0f, 0.0f, 1.0f, false, false);
                }
                ctx->OMSetDepthStencilState(r->dss_default.Get(), 0);
            }
        }
    }

    /* ---- PassC：最终光照（或 debug 通道）→ 后备缓冲（仅 deferred 模式） ---- */
    if (use_deferred) {
        ID3D11RenderTargetView *bb[1] = { r->rtv.Get() };
        ctx->OMSetRenderTargets(1, bb, r->dsv.Get());
        ctx->VSSetShader(r->vs_fs.Get(), nullptr, 0);
        ctx->PSSetShader(r->ps_fs.Get(), nullptr, 0);
        ctx->OMSetDepthStencilState(r->dss_no_write.Get(), 0);
        ctx->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        bind_scene_srvs(r, nullptr, r->nb_srv.Get());
        const int dbg = (int)r->frame.debug_mode;
        /* debug 5(art 覆盖强度) / 6(matId) 的值由 Pass1 写进 albedo 附件，
         * 全屏 pass 用 mode 16 原样取出（直出路径则是材质 shader 直接返回）。 */
        const int fs_mode = (dbg == 2) ? 12 : (dbg == 3) ? 13 : (dbg == 4) ? 14
                          : (dbg == 7) ? 15 : (dbg == 5 || dbg == 6) ? 16 : 11;
        draw_fullscreen(r, fs_mode);
        unbind_scene_srvs(r);
        ctx->OMSetDepthStencilState(r->dss_default.Get(), 0);
    }

    /* ---- 无光照 / 透明 pass（emissive / grid / glass / 有色的贴花） ---- */
    /* ⚠️ 必须重设实体 VS：PassC 把 VS 切成了全屏变体（vs_fs），
     *    否则实体几何会按全屏三角形绘制 → 整屏被盖住（deferred 失效的真正原因）。 */
    ctx->VSSetShader(r->vs.Get(), nullptr, 0);
    ctx->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    ctx->OMSetBlendState(r->bs_alpha.Get(), blend_factor, 0xFFFFFFFF);
    ctx->OMSetDepthStencilState(r->dss_no_write.Get(), 0);
    for (MeshRes &m : r->meshes) {
        if (!m.visible || m.index_count == 0) continue;
        if (m.kind != WSR_MESH_HULL && m.kind != WSR_MESH_MOUNT) continue;
        if (armor_mode) continue;
        if (m.kind == WSR_MESH_HULL && !r->view.show_hull) continue;
        if (m.kind == WSR_MESH_MOUNT && !r->view.show_mounts) continue;
        const uint32_t fam = m.mat.family;
        if (fam != WSR_FAM_EMISSIVE && fam != WSR_FAM_UNLIT) continue;

        const float em_on = (fam == WSR_FAM_EMISSIVE) ? 1.0f : 0.0f;
        const float em_k  = (fam == WSR_FAM_EMISSIVE) ? m.mat.emissive_k : 1.0f;
        const float op    = m.mat.opacity;
        draw_one(r, m, 2, nullptr, true, op, em_on, em_k, matid_vis, false);
    }
    ctx->OMSetBlendState(r->bs_opaque.Get(), blend_factor, 0xFFFFFFFF);
    ctx->OMSetDepthStencilState(r->dss_default.Get(), 0);

    /* ---- 装甲 pass（与旧版一致：平涂 + 深度偏移 + alpha；边界线不写深度） ---- */
    if (r->view.show_armor) {
        ctx->VSSetShader(r->vs.Get(), nullptr, 0);
        ctx->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        /* 1) 装甲平涂：略拉向相机避免与船体 z-fight，按不透明度混合 */
        ctx->RSSetState(r->rs_bias1.Get());
        ctx->OMSetBlendState(r->bs_alpha.Get(), blend_factor, 0xFFFFFFFF);
        for (MeshRes &m : r->meshes) {
            if (!m.visible || m.index_count == 0 || m.kind != WSR_MESH_ARMOR) continue;
            if (m.mat.flags & WSR_MESHF_LINES) continue;
            draw_one(r, m, 2, nullptr, true, r->view.armor_opacity, 0.0f, 1.0f, false, false);
        }
        /* 2) 板块边界线：更强偏移 + 不写深度 + 不做 alpha 混合 */
        ctx->RSSetState(r->rs_bias2.Get());
        ctx->OMSetDepthStencilState(r->dss_no_write.Get(), 0);
        ctx->OMSetBlendState(r->bs_opaque.Get(), blend_factor, 0xFFFFFFFF);
        for (MeshRes &m : r->meshes) {
            if (!m.visible || m.index_count == 0 || m.kind != WSR_MESH_ARMOR) continue;
            if (!(m.mat.flags & WSR_MESHF_LINES)) continue;
            draw_one(r, m, 2, nullptr, true, m.mat.opacity, 0.0f, 1.0f, false, false);
        }
        ctx->RSSetState(r->rs_solid.Get());
        ctx->OMSetDepthStencilState(r->dss_default.Get(), 0);
    }

    const UINT sync_interval = (r->flags & WSR_FLAG_NO_VSYNC) ? 0u : 1u;
    HRESULT hr = r->swapchain->Present(sync_interval, 0);

    if (is_device_lost(hr) || hr == DXGI_ERROR_DRIVER_INTERNAL_ERROR) {
        r->device_lost_count++;
        if (!rebuild(r)) {
            const std::string why = g_last_error;
            return fail(WSR_ERR_DEVICE, "wsr_render: device lost, rebuild failed: %s", why.c_str());
        }
        return WSR_OK; /* 待调用方重新提交场景 */
    }
    if (FAILED(hr)) {
        return fail(WSR_ERR_SWAPCHAIN, "wsr_render: Present failed (hr=0x%08X)",
                    static_cast<unsigned>(hr));
    }

    r->frame_index++;
    sample_frame_time(r);
    return WSR_OK;
}

/* ============================ 纹理 / 场景 / 帧 ============================ */

int32_t wsr_texture_upload(wsr_renderer *r, const char *key, const wsr_texture_desc *desc)
{
    if (r == nullptr || key == nullptr || desc == nullptr || desc->data == nullptr) {
        return fail(WSR_ERR_INVALID_ARG, "wsr_texture_upload: null argument");
    }
    if (desc->width == 0 || desc->height == 0 || desc->mip_count == 0) {
        return fail(WSR_ERR_INVALID_ARG, "wsr_texture_upload: invalid dimensions");
    }

    const uint32_t array_size = (desc->array_size > 0) ? desc->array_size : 1u;

    D3D11_TEXTURE2D_DESC td = {};
    td.Width            = desc->width;
    td.Height           = desc->height;
    td.MipLevels        = desc->mip_count;
    td.ArraySize        = array_size;
    td.Format           = static_cast<DXGI_FORMAT>(desc->format);
    td.SampleDesc.Count = 1;
    td.Usage            = D3D11_USAGE_DEFAULT;
    td.BindFlags        = D3D11_BIND_SHADER_RESOURCE;

    const uint8_t *base = static_cast<const uint8_t *>(desc->data);

    ComPtr<ID3D11Texture2D> tex;
    HRESULT hr = r->device->CreateTexture2D(&td, nullptr, tex.ReleaseAndGetAddressOf());
    if (FAILED(hr)) {
        return fail(WSR_ERR_INTERNAL,
                    "wsr_texture_upload('%s'): CreateTexture2D failed (hr=0x%08X) "
                    "w=%u h=%u fmt=%u arr=%u mips=%u mip0=%u data=%llu",
                    key, static_cast<unsigned>(hr),
                    desc->width, desc->height, desc->format, array_size, desc->mip_count,
                    (desc->mip_sizes != nullptr) ? desc->mip_sizes[0] : 0u,
                    static_cast<unsigned long long>(desc->data_size));
    }

    /* 逐 subresource 上传（顺序 = mip + slice * mipCount，与 D3D 约定一致） */
    for (uint32_t mip = 0; mip < desc->mip_count; ++mip) {
        const uint32_t off = desc->mip_offsets ? desc->mip_offsets[mip] : 0u;
        const uint32_t sz  = desc->mip_sizes ? desc->mip_sizes[mip] : 0u;
        const uint8_t *pmip = base + off;
        const uint32_t per_slice = (array_size > 0) ? (sz / array_size) : sz;
        for (uint32_t slice = 0; slice < array_size; ++slice) {
            const UINT sub = D3D11CalcSubresource(mip, slice, desc->mip_count);
            r->ctx->UpdateSubresource(tex.Get(), sub, nullptr,
                                      pmip + static_cast<size_t>(per_slice) * slice, 0, 0);
        }
    }

    D3D11_SHADER_RESOURCE_VIEW_DESC sv = {};
    sv.Format = td.Format;
    if (array_size > 1) {
        sv.ViewDimension = D3D11_SRV_DIMENSION_TEXTURE2DARRAY;
        sv.Texture2DArray.MostDetailedMip = 0;
        sv.Texture2DArray.MipLevels       = desc->mip_count;
        sv.Texture2DArray.FirstArraySlice = 0;
        sv.Texture2DArray.ArraySize       = array_size;
    } else {
        sv.ViewDimension = D3D11_SRV_DIMENSION_TEXTURE2D;
        sv.Texture2D.MostDetailedMip = 0;
        sv.Texture2D.MipLevels       = desc->mip_count;
    }

    TextureRes res;
    res.kind = (array_size > 1) ? WSR_TEXKIND_2D_ARRAY : WSR_TEXKIND_2D;
    hr = r->device->CreateShaderResourceView(tex.Get(), &sv, res.srv.ReleaseAndGetAddressOf());
    if (FAILED(hr)) {
        return fail(WSR_ERR_INTERNAL, "wsr_texture_upload('%s'): CreateSRV failed (hr=0x%08X)",
                    key, static_cast<unsigned>(hr));
    }

    r->textures[key] = std::move(res);
    return WSR_OK;
}

int32_t wsr_texture_clear(wsr_renderer *r)
{
    if (r == nullptr) {
        return fail(WSR_ERR_INVALID_ARG, "wsr_texture_clear: renderer is null");
    }
    r->textures.clear();
    return WSR_OK;
}

int32_t wsr_scene_begin(wsr_renderer *r)
{
    if (r == nullptr) {
        return fail(WSR_ERR_INVALID_ARG, "wsr_scene_begin: renderer is null");
    }
    return WSR_OK;
}

int32_t wsr_scene_add_mesh(wsr_renderer *r, const wsr_mesh_desc *desc)
{
    if (r == nullptr || desc == nullptr || desc->key == nullptr) {
        return fail(WSR_ERR_INVALID_ARG, "wsr_scene_add_mesh: null argument");
    }
    if (desc->vertices == nullptr || desc->vertex_count == 0 ||
        desc->indices == nullptr || desc->index_count == 0) {
        return fail(WSR_ERR_INVALID_ARG, "wsr_scene_add_mesh('%s'): empty geometry", desc->key);
    }

    MeshRes m;
    m.key            = desc->key;
    m.kind           = desc->kind;
    m.index_count    = desc->index_count;
    m.vertex_count   = desc->vertex_count;
    m.instance_count = desc->instance_count;
    m.mat.family     = desc->family;
    m.mat.flags      = desc->flags;
    m.mat.opacity    = (desc->opacity > 0.0f) ? desc->opacity : 1.0f;
    m.mat.emissive_k = desc->emissive_k;
    for (int i = 0; i < WSR_TEX_COUNT; ++i) {
        if (desc->textures[i] != nullptr && desc->textures[i][0] != '\0') {
            m.mat.tex[i] = desc->textures[i];
        }
    }

    const uint32_t n = desc->matid_count;
    const auto fill_arr = [&](std::vector<float> &dst, const float *src) {
        if (src != nullptr && n > 0) {
            dst.assign(src, src + static_cast<size_t>(n) * 4u);
        }
    };
    m.mat.matid_count = n;
    fill_arr(m.mat.offset_scale, desc->arr_offset_scale);
    fill_arr(m.mat.rotation,     desc->arr_rotation);
    fill_arr(m.mat.tile_idx,     desc->arr_tile_idx);
    fill_arr(m.mat.tint,         desc->arr_tint);
    fill_arr(m.mat.remove,       desc->arr_remove);

    if (desc->model_matrix != nullptr) {
        memcpy(m.model, desc->model_matrix, sizeof(m.model));
        m.has_model = true;
    }

    /* VTX */
    D3D11_BUFFER_DESC bd = {};
    bd.Usage          = D3D11_USAGE_IMMUTABLE;
    bd.BindFlags      = D3D11_BIND_VERTEX_BUFFER;
    bd.ByteWidth      = desc->vertex_count * VERTEX_STRIDE;
    D3D11_SUBRESOURCE_DATA init = {};
    init.pSysMem = desc->vertices;
    HRESULT hr = r->device->CreateBuffer(&bd, &init, m.vb.ReleaseAndGetAddressOf());
    if (FAILED(hr)) {
        return fail(WSR_ERR_INTERNAL, "wsr_scene_add_mesh('%s'): VB failed (hr=0x%08X)",
                    desc->key, static_cast<unsigned>(hr));
    }

    /* IB */
    bd.BindFlags = D3D11_BIND_INDEX_BUFFER;
    bd.ByteWidth = desc->index_count * sizeof(uint32_t);
    init.pSysMem = desc->indices;
    hr = r->device->CreateBuffer(&bd, &init, m.ib.ReleaseAndGetAddressOf());
    if (FAILED(hr)) {
        return fail(WSR_ERR_INTERNAL, "wsr_scene_add_mesh('%s'): IB failed (hr=0x%08X)",
                    desc->key, static_cast<unsigned>(hr));
    }

    /* 实例矩阵：统一成「至少 1 个」的实例数组（model_matrix 作为单实例） */
    static const float kIdentity16[16] = {
        1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1
    };
    const float *inst_src = kIdentity16;
    uint32_t inst_n = 1;
    if (desc->instance_count > 0 && desc->instance_matrices != nullptr) {
        inst_src = desc->instance_matrices;
        inst_n = desc->instance_count;
    } else if (desc->model_matrix != nullptr) {
        inst_src = desc->model_matrix;
        inst_n = 1;
    }
    bd.BindFlags = D3D11_BIND_VERTEX_BUFFER;
    bd.ByteWidth = inst_n * 16u * sizeof(float);
    init.pSysMem = inst_src;
    hr = r->device->CreateBuffer(&bd, &init, m.inst_vb.ReleaseAndGetAddressOf());
    if (FAILED(hr)) {
        return fail(WSR_ERR_INTERNAL, "wsr_scene_add_mesh('%s'): inst VB failed (hr=0x%08X)",
                    desc->key, static_cast<unsigned>(hr));
    }
    m.instance_count = inst_n;

    auto it = r->mesh_index.find(m.key);
    if (it != r->mesh_index.end()) {
        const size_t slot = it->second;
        const bool visible = r->meshes[slot].visible;
        r->meshes[slot] = std::move(m);
        r->meshes[slot].visible = visible;
        r->dup_mesh_keys++;
    } else {
        r->mesh_index[m.key] = r->meshes.size();
        r->meshes.push_back(std::move(m));
    }
    return WSR_OK;
}

int32_t wsr_scene_end(wsr_renderer *r)
{
    if (r == nullptr) {
        return fail(WSR_ERR_INVALID_ARG, "wsr_scene_end: renderer is null");
    }
    r->need_resubmit = false;
    return WSR_OK;
}

int32_t wsr_scene_clear(wsr_renderer *r)
{
    if (r == nullptr) {
        return fail(WSR_ERR_INVALID_ARG, "wsr_scene_clear: renderer is null");
    }
    r->meshes.clear();
    r->mesh_index.clear();
    r->dup_mesh_keys = 0;
    return WSR_OK;
}

int32_t wsr_frame_set(wsr_renderer *r, const wsr_frame_params *p)
{
    if (r == nullptr || p == nullptr) {
        return fail(WSR_ERR_INVALID_ARG, "wsr_frame_set: null argument");
    }
    memcpy(&r->frame, p, sizeof(wsr_frame_params));
    r->frame_valid = true;

    /* 全屏 pass 的常量模板（光照参数；mvp 不参与） */
    FrameCBData fc = {};
    memcpy(fc.light_dir, p->light_dir, 3 * sizeof(float));
    memcpy(fc.ambient, p->ambient, 3 * sizeof(float));
    memcpy(fc.light_pos, p->light_pos, 3 * sizeof(float));
    fc.view_dir[0] = p->view[8];
    fc.view_dir[1] = p->view[9];
    fc.view_dir[2] = p->view[10];
    fc.params[0] = p->normal_strength;
    fc.params[1] = p->opacity;
    r->fs_template = fc;
    return WSR_OK;
}

int32_t wsr_view_options_set(wsr_renderer *r, const wsr_view_options *o)
{
    if (r == nullptr || o == nullptr) {
        return fail(WSR_ERR_INVALID_ARG, "wsr_view_options_set: null argument");
    }
    r->view = *o;
    if (o->clear_color[0] != 0.0f || o->clear_color[1] != 0.0f ||
        o->clear_color[2] != 0.0f || o->clear_color[3] != 0.0f) {
        for (int i = 0; i < 4; ++i) {
            r->clear_color[i] = o->clear_color[i];
        }
    }
    return WSR_OK;
}

int32_t wsr_mesh_set_visible(wsr_renderer *r, const char *key, uint32_t visible)
{
    if (r == nullptr || key == nullptr) {
        return fail(WSR_ERR_INVALID_ARG, "wsr_mesh_set_visible: null argument");
    }
    auto it = r->mesh_index.find(key);
    if (it == r->mesh_index.end()) {
        return fail(WSR_ERR_INVALID_ARG, "wsr_mesh_set_visible: unknown mesh '%s'", key);
    }
    r->meshes[it->second].visible = (visible != 0);
    return WSR_OK;
}

int32_t wsr_mesh_set_indices(wsr_renderer *r, const char *key,
                             const uint32_t *indices, uint32_t count)
{
    if (r == nullptr || key == nullptr) {
        return fail(WSR_ERR_INVALID_ARG, "wsr_mesh_set_indices: null argument");
    }
    auto it = r->mesh_index.find(key);
    if (it == r->mesh_index.end()) {
        return fail(WSR_ERR_INVALID_ARG, "wsr_mesh_set_indices: unknown mesh '%s'", key);
    }
    MeshRes &m = r->meshes[it->second];
    if (indices == nullptr || count == 0) {
        m.index_count = 0;
        return WSR_OK;
    }
    /* 动态索引缓冲：重建为 DEFAULT 用法（内容不常变，只变化一次） */
    D3D11_BUFFER_DESC bd = {};
    bd.Usage     = D3D11_USAGE_DEFAULT;
    bd.BindFlags = D3D11_BIND_INDEX_BUFFER;
    bd.ByteWidth = count * sizeof(uint32_t);
    D3D11_SUBRESOURCE_DATA init = {};
    init.pSysMem = indices;
    ComPtr<ID3D11Buffer> nb;
    HRESULT hr = r->device->CreateBuffer(&bd, &init, nb.ReleaseAndGetAddressOf());
    if (FAILED(hr)) {
        return fail(WSR_ERR_INTERNAL, "wsr_mesh_set_indices('%s'): failed (hr=0x%08X)",
                    key, static_cast<unsigned>(hr));
    }
    m.ib = nb;
    m.index_count = count;
    return WSR_OK;
}

int32_t wsr_mesh_set_highlight(wsr_renderer *r, const char *key,
                               const uint32_t *indices, uint32_t count)
{
    /* 高亮叠加层在后续阶段接入（需独立 IB + 绘制 pass）；当前仅校验参数，
     * 避免调用方误以为生效。 */
    if (r == nullptr || key == nullptr) {
        return fail(WSR_ERR_INVALID_ARG, "wsr_mesh_set_highlight: null argument");
    }
    if (r->mesh_index.find(key) == r->mesh_index.end()) {
        return fail(WSR_ERR_INVALID_ARG, "wsr_mesh_set_highlight: unknown mesh '%s'", key);
    }
    (void)indices;
    (void)count;
    return WSR_OK;
}

int32_t wsr_scene_stats(wsr_renderer *r, uint32_t *mesh_count, uint32_t *texture_count)
{
    if (r == nullptr) {
        return fail(WSR_ERR_INVALID_ARG, "wsr_scene_stats: renderer is null");
    }
    if (mesh_count) {
        *mesh_count = static_cast<uint32_t>(r->meshes.size());
    }
    if (texture_count) {
        *texture_count = static_cast<uint32_t>(r->textures.size());
    }
    return WSR_OK;
}

int32_t wsr_needs_resubmit(wsr_renderer *r)
{
    if (r == nullptr) {
        return fail(WSR_ERR_INVALID_ARG, "wsr_needs_resubmit: renderer is null");
    }
    return r->need_resubmit ? 1 : 0;
}

int32_t wsr_capture_bmp(wsr_renderer *r, const char *path)
{
    if (r == nullptr || path == nullptr) {
        return fail(WSR_ERR_INVALID_ARG, "wsr_capture_bmp: null argument");
    }
    if (!r->swapchain) {
        return fail(WSR_ERR_DEVICE, "wsr_capture_bmp: no swapchain");
    }

    ComPtr<ID3D11Texture2D> back;
    HRESULT hr = r->swapchain->GetBuffer(0, IID_PPV_ARGS(back.ReleaseAndGetAddressOf()));
    if (FAILED(hr)) {
        return fail(WSR_ERR_SWAPCHAIN, "wsr_capture_bmp: GetBuffer failed (hr=0x%08X)",
                    static_cast<unsigned>(hr));
    }

    D3D11_TEXTURE2D_DESC dd = {};
    back->GetDesc(&dd);
    D3D11_TEXTURE2D_DESC sd = dd;
    sd.Usage          = D3D11_USAGE_STAGING;
    sd.BindFlags      = 0;
    sd.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    sd.MiscFlags      = 0;

    ComPtr<ID3D11Texture2D> staging;
    hr = r->device->CreateTexture2D(&sd, nullptr, staging.ReleaseAndGetAddressOf());
    if (FAILED(hr)) {
        return fail(WSR_ERR_INTERNAL, "wsr_capture_bmp: staging failed (hr=0x%08X)",
                    static_cast<unsigned>(hr));
    }
    r->ctx->CopyResource(staging.Get(), back.Get());

    D3D11_MAPPED_SUBRESOURCE ms = {};
    hr = r->ctx->Map(staging.Get(), 0, D3D11_MAP_READ, 0, &ms);
    if (FAILED(hr)) {
        return fail(WSR_ERR_INTERNAL, "wsr_capture_bmp: Map failed (hr=0x%08X)",
                    static_cast<unsigned>(hr));
    }

    const uint32_t w = dd.Width;
    const uint32_t h = dd.Height;
    const uint32_t row_bytes = w * 4u;
    const uint32_t img_bytes = row_bytes * h;
    const uint32_t file_size = 54u + img_bytes;

    uint8_t header[54] = {};
    header[0] = 'B';
    header[1] = 'M';
    const auto put32 = [&](int off, uint32_t v) {
        header[off + 0] = (uint8_t)(v & 0xFF);
        header[off + 1] = (uint8_t)((v >> 8) & 0xFF);
        header[off + 2] = (uint8_t)((v >> 16) & 0xFF);
        header[off + 3] = (uint8_t)((v >> 24) & 0xFF);
    };
    const auto put16 = [&](int off, uint16_t v) {
        header[off + 0] = (uint8_t)(v & 0xFF);
        header[off + 1] = (uint8_t)((v >> 8) & 0xFF);
    };
    put32(2, file_size);
    put32(10, 54);
    put32(14, 40);          /* BITMAPINFOHEADER */
    put32(18, (int32_t)w);
    put32(22, (int32_t)h);
    put16(26, 1);           /* planes */
    put16(28, 32);          /* bpp */
    put32(34, img_bytes);

    FILE *f = nullptr;
    if (fopen_s(&f, path, "wb") != 0 || f == nullptr) {
        r->ctx->Unmap(staging.Get(), 0);
        return fail(WSR_ERR_INTERNAL, "wsr_capture_bmp: cannot open '%s'", path);
    }
    fwrite(header, 1, sizeof(header), f);
    /* BMP 行序自下而上；D3D staging 也自顶向下 ⇒ 反向写入 */
    const uint8_t *src = static_cast<const uint8_t *>(ms.pData);
    for (int y = (int)h - 1; y >= 0; --y) {
        fwrite(src + static_cast<size_t>(y) * ms.RowPitch, 1, row_bytes, f);
    }
    fclose(f);
    r->ctx->Unmap(staging.Get(), 0);
    return WSR_OK;
}

int32_t wsr_diag_state(wsr_renderer *r, uint32_t *flags)
{
    if (r == nullptr || flags == nullptr) {
        return fail(WSR_ERR_INVALID_ARG, "wsr_diag_state: null argument");
    }
    uint32_t f = 0;
    if (r->vs)              f |= 1u << 0;
    if (r->ps)              f |= 1u << 1;
    if (r->ps_mrt)          f |= 1u << 2;
    if (r->vs_fs)           f |= 1u << 3;
    if (r->ps_fs)           f |= 1u << 4;
    if (r->scene_albedo_rtv && r->scene_normal_rtv && r->scene_world_rtv) f |= 1u << 5;
    if (r->na_rtv && r->nb_rtv) f |= 1u << 6;
    if (r->layout)          f |= 1u << 7;
    if (r->cb_frame && r->cb_mat && r->cb_indexed) f |= 1u << 8;
    if (r->dup_mesh_keys == 0) f |= 1u << 9;   /* bit9=1：本次场景 key 唯一（无静默丢网格） */
    *flags = f;
    return WSR_OK;
}

int32_t wsr_stats_get(wsr_renderer *r, wsr_stats *out)
{
    if (r == nullptr || out == nullptr) {
        return fail(WSR_ERR_INVALID_ARG, "wsr_stats_get: null argument");
    }
    out->draw_calls        = r->draw_calls;
    out->device_lost_count = r->device_lost_count;
    out->frame_index       = r->frame_index;
    out->frame_ms_last     = static_cast<float>(r->frame_ms_last);
    out->frame_ms_avg      = static_cast<float>(r->frame_ms_avg);
    return WSR_OK;
}

const char *wsr_last_error(void)
{
    return g_last_error.c_str();
}

int32_t wsr_debug_simulate_device_lost(wsr_renderer *r)
{
    if (r == nullptr) {
        return fail(WSR_ERR_INVALID_ARG, "wsr_debug_simulate_device_lost: renderer is null");
    }
    r->simulate_lost = true;
    return WSR_OK;
}

} /* extern "C" */
