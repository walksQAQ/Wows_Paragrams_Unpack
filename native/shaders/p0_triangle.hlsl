/*
 * p0_triangle.hlsl —— P0 骨架专用最小着色器。
 *
 * 仅用于验证：DLL 加载 / 交换链呈现 / resize / DPI / 设备丢失恢复。
 * P1 起由 PBR / INDEXED / decal / overlay 等着色器族替换，
 * 届时材质算法必须逐项搬运自有已验证的 GLSL 实现（见架构文档 §1.4）。
 */

struct VSInput
{
    float3 position : POSITION;
    float4 color    : COLOR;
};

struct VSOutput
{
    float4 position : SV_POSITION;
    float4 color    : COLOR;
};

VSOutput VSMain(VSInput input)
{
    VSOutput output;
    output.position = float4(input.position, 1.0f);
    output.color    = input.color;
    return output;
}

float4 PSMain(VSOutput input) : SV_TARGET
{
    return input.color;
}
