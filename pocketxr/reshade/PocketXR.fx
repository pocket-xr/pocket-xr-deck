// Pocket XR for Steam Deck, Gaming Mode: the whole Gaming Mode picture as a screen held still in space.
//
// gamescope runs this effect on the app's picture (its first layer; the mouse cursor and Steam's overlays are drawn
// after it, unchanged: gamescope's vulkan_composite), the frame it sends to the glasses. Pocket XR's Gaming Mode
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
// z: curve, 0 flat to 1 (the screen bent round the eye, every part of it as far away as the middle).
uniform float4 pxr_mode < source = "pxr_mode"; >;
// The mouse pointer, drawn here so it sits over what it points at on the moved screen (gamescope's own cursor is
// drawn after this effect, where the pointer is on the Deck's screen). x, y: where, 0 to 1 across and down the
// picture. z: 1 to draw it. w: unused.
uniform float4 pxr_cursor < source = "pxr_cursor"; >;
// Keeps gamescope painting every frame, so the screen stays put as the head turns over a still game.
uniform bool pxr_always_paint < source = "gamescope_always_paint"; >;

float3 pxr_rotate(float4 q, float3 v)
{
    float3 t = 2.0 * cross(q.xyz, v);
    return v + q.w * t + cross(q.xyz, t);
}

// How far a point is on the inner side of the edge p0-p1 (the side the third corner is on), in pixels.
float pxr_edge(float2 p, float2 p0, float2 p1, float2 other)
{
    float2 n = normalize(float2(p1.y - p0.y, p0.x - p1.x));
    return dot(p - p0, n) * sign(dot(other - p0, n));
}

// How far inside the pointer's arrow a picture pixel is (positive inside), in picture pixels: tip at (0, 0), y down.
float pxr_arrow(float2 p)
{
    float2 a = float2(0.0, 0.0), b = float2(0.0, 17.0), c = float2(12.0, 12.0);
    return min(pxr_edge(p, a, b, c), min(pxr_edge(p, b, c, a), pxr_edge(p, c, a, b)));
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

    // Where it meets the screen, straight ahead of the recentred forward, its middle 1 away.
    float2 uv;
    float bend = pxr_mode.z;
    if (bend < 0.001)
    {
        float2 onScreen = room.xy / -room.z;
        uv = float2(0.5 + onScreen.x / (2.0 * pxr_view.z), 0.5 - onScreen.y / (2.0 * pxr_view.w));
    }
    else
    {
        // Curved: part of an upright cylinder of radius 1 / bend, its middle where the flat screen's is, bent
        // towards the eye. The screen keeps its width along the curve, and stays straight up and down.
        float r = 1.0 / bend;
        float cz = r - 1.0;            // the cylinder's axis, at z = cz (behind the eye for bend < 1)
        float a = room.x * room.x + room.z * room.z;
        float b = room.z * cz;         // the eye is inside the cylinder: one meeting point ahead
        float t = (b + sqrt(max(b * b - a * (cz * cz - r * r), 0.0))) / max(a, 0.000001);
        float3 hit = room * t;
        float across = atan2(hit.x, cz - hit.z) * r;
        uv = float2(0.5 + across / (2.0 * pxr_view.z), 0.5 - hit.y / (2.0 * pxr_view.w));
    }
    if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0)
        return float4(0.0, 0.0, 0.0, 1.0);

    // A soft edge, so the screen's border doesn't shimmer.
    float2 edge = min(uv, 1.0 - uv) / max(pxr_mode.y, 0.0001);
    float fade = saturate(min(edge.x, edge.y));
    float3 colour = tex2D(PxrBackBuffer, uv).rgb;
    if (pxr_cursor.z > 0.5)
    {
        // The arrow, a little bigger on bigger pictures: white with a dark edge, as a desktop pointer.
        float scale = max(1.0, BUFFER_HEIGHT / 800.0);
        float2 p = (uv - pxr_cursor.xy) * float2(BUFFER_WIDTH, BUFFER_HEIGHT) / scale;
        float inside = pxr_arrow(p);
        if (inside > 1.2)
            colour = float3(1.0, 1.0, 1.0);
        else if (inside > -0.6)
            colour = float3(0.05, 0.05, 0.05);
    }
    return float4(colour * fade, 1.0);
}

technique PocketXR
{
    pass
    {
        VertexShader = PxrVS;
        PixelShader = PxrPS;
    }
}
