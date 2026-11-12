// Pocket XR for Steam Deck, Gaming Mode: the whole Gaming Mode picture as a screen held still in space.
//
// gamescope runs this effect on its finished picture, the frame it sends to the glasses. Pocket XR's Gaming Mode
// service (pocketxr/gaming.py) sends the head's turn through gamescope's reshade interface many times a second. For
// each pixel of the glasses' picture the effect works out where that pixel looks, in the room, and shows what the
// screen has there, or black (see-through on the glasses) where the screen isn't.
//
// The values come from the service by name: a uniform with a "source" annotation is one gamescope lets a program set.
// GPL-3.0, as Pocket XR.

texture PxrBackBufferTex : COLOR;
sampler PxrBackBuffer { Texture = PxrBackBufferTex; AddressU = CLAMP; AddressV = CLAMP; MinFilter = LINEAR; MagFilter = LINEAR; };

// The head's turn from the recentred forward, as a quaternion x, y, z, w (room from head).
uniform float4 pxr_quat < source = "pxr_quat"; >;
// x, y: tangents of half the glasses' picture across and up. z, w: tangents of half the screen across and up.
uniform float4 pxr_view < source = "pxr_view"; >;
// x: 1 to draw the screen in space, 0 to pass the picture through as it is. y: soft edge, in screen widths.
uniform float4 pxr_mode < source = "pxr_mode"; >;
// Keeps gamescope painting every frame, so the screen stays put as the head turns over a still game.
uniform bool pxr_always_paint < source = "gamescope_always_paint"; >;

float3 pxr_rotate(float4 q, float3 v)
{
    float3 t = 2.0 * cross(q.xyz, v);
    return v + q.w * t + cross(q.xyz, t);
}

void PxrVS(in uint id : SV_VertexID, out float4 position : SV_Position, out float2 texcoord : TEXCOORD)
{
    texcoord.x = (id == 2) ? 2.0 : 0.0;
    texcoord.y = (id == 1) ? 2.0 : 0.0;
    position = float4(texcoord * float2(2.0, -2.0) + float2(-1.0, 1.0), 0.0, 1.0);
}

float4 PxrPS(float4 position : SV_Position, float2 texcoord : TEXCOORD) : SV_Target
{
    if (pxr_mode.x < 0.5)
        return tex2D(PxrBackBuffer, texcoord);

    // This pixel's direction from the eye: x right, y up, looking along -z.
    float3 eye = float3((texcoord.x * 2.0 - 1.0) * pxr_view.x, (1.0 - texcoord.y * 2.0) * pxr_view.y, -1.0);
    float3 room = pxr_rotate(pxr_quat, eye);
    if (room.z > -0.05)
        return float4(0.0, 0.0, 0.0, 1.0);

    // Where it meets the screen, straight ahead of the recentred forward.
    float2 onScreen = room.xy / -room.z;
    float2 uv = float2(0.5 + onScreen.x / (2.0 * pxr_view.z), 0.5 - onScreen.y / (2.0 * pxr_view.w));
    if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0)
        return float4(0.0, 0.0, 0.0, 1.0);

    // A soft edge, so the screen's border doesn't shimmer.
    float2 edge = min(uv, 1.0 - uv) / max(pxr_mode.y, 0.0001);
    float fade = saturate(min(edge.x, edge.y));
    return float4(tex2D(PxrBackBuffer, uv).rgb * fade, 1.0);
}

technique PocketXR
{
    pass
    {
        VertexShader = PxrVS;
        PixelShader = PxrPS;
    }
}
