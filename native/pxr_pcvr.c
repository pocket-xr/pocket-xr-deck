// PC VR on the Steam Deck: Pocket XR's bridge to ALVR's client library (alvr_client_core, MIT licence).
//
// The same as Pocket XR's Android bridge (app/src/main/cpp/pocketxr_alvr.cpp), but ALVR's video is decoded here:
// ALVR hands each encoded frame to decoder_input(); FFmpeg decodes it on the Deck's GPU (VA-API) and the newest frame
// is copied out as NV12. pxr_acquire(), on the app's GL thread, puts it into two textures (Y and UV) for the app's
// shader. Everything else (events, view params, tracking, buttons) is ALVR's C interface as on Android.
//
// Built against FFmpeg 7.1's headers and the Deck's own libavcodec.so.61 / libavutil.so.59 (SteamOS 3.7).

#include <GL/gl.h>
#include <libavcodec/avcodec.h>
#include <libavutil/hwcontext.h>
#include <libavutil/imgutils.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "alvr_client_core.h"

#define LOG(...) do { fprintf(stderr, "pxr_pcvr: " __VA_ARGS__); fputc('\n', stderr); } while (0)

static int g_initialized = 0;
static uint64_t g_head_id = 0;

// ---------------- decoding ----------------
static AVCodecContext *g_dec = NULL;
static AVBufferRef *g_hw = NULL;
static AVFrame *g_hwframe = NULL;
static AVFrame *g_swframe = NULL;
static AVPacket *g_packet = NULL;
static int g_hw_ok = 0;
// Held while the decoder is used or replaced: ALVR's thread feeds it while the app's thread may set it up.
static pthread_mutex_t g_dec_lock = PTHREAD_MUTEX_INITIALIZER;

// The newest decoded frame, NV12, for the GL thread.
static pthread_mutex_t g_lock = PTHREAD_MUTEX_INITIALIZER;
static uint8_t *g_y = NULL, *g_uv = NULL;
static int g_w = 0, g_h = 0, g_cap = 0;
static uint64_t g_ts = 0;
static int g_fresh = 0;
static uint64_t g_decoded = 0, g_errors = 0;

static uint64_t now_ns(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000000000ull + (uint64_t)t.tv_nsec;
}

static enum AVPixelFormat pick_vaapi(AVCodecContext *c, const enum AVPixelFormat *fmts) {
    (void)c;
    for (const enum AVPixelFormat *p = fmts; *p != AV_PIX_FMT_NONE; p++)
        if (*p == AV_PIX_FMT_VAAPI) return *p;
    LOG("the decoder offered no VA-API format; decoding on the CPU");
    return fmts[0];
}

static void keep_frame(const AVFrame *f, uint64_t ts) {
    // NV12 from VA-API (or yuv420p from the CPU decoder, interleaved here into NV12).
    const int w = f->width, h = f->height;
    pthread_mutex_lock(&g_lock);
    if (g_cap < w * h) {
        free(g_y);
        free(g_uv);
        g_y = malloc((size_t)w * h);
        g_uv = malloc((size_t)w * h / 2);
        g_cap = w * h;
    }
    for (int r = 0; r < h; r++) memcpy(g_y + (size_t)r * w, f->data[0] + (size_t)r * f->linesize[0], w);
    if (f->format == AV_PIX_FMT_NV12) {
        for (int r = 0; r < h / 2; r++) memcpy(g_uv + (size_t)r * w, f->data[1] + (size_t)r * f->linesize[1], w);
    } else {
        for (int r = 0; r < h / 2; r++) {
            const uint8_t *u = f->data[1] + (size_t)r * f->linesize[1];
            const uint8_t *v = f->data[2] + (size_t)r * f->linesize[2];
            uint8_t *o = g_uv + (size_t)r * w;
            for (int c = 0; c < w / 2; c++) {
                o[2 * c] = u[c];
                o[2 * c + 1] = v[c];
            }
        }
    }
    g_w = w;
    g_h = h;
    g_ts = ts;
    g_fresh = 1;
    pthread_mutex_unlock(&g_lock);
}

// ALVR's thread: one encoded frame (NAL units). Decoded here, at once.
static bool decoder_input(AlvrVideoFrameData d) {
    pthread_mutex_lock(&g_dec_lock);
    if (!g_dec) {
        pthread_mutex_unlock(&g_dec_lock);
        return false;
    }
    g_packet->data = (uint8_t *)d.buffer_ptr;
    g_packet->size = (int)d.buffer_size;
    g_packet->pts = (int64_t)d.timestamp_ns;
    int r = avcodec_send_packet(g_dec, g_packet);
    if (r < 0 && r != AVERROR(EAGAIN)) {
        g_errors++;
        pthread_mutex_unlock(&g_dec_lock);
        return true;  // a bad frame is dropped; the next key frame recovers
    }
    for (;;) {
        r = avcodec_receive_frame(g_dec, g_hwframe);
        if (r < 0) break;
        const AVFrame *out = g_hwframe;
        if (g_hwframe->format == AV_PIX_FMT_VAAPI) {
            g_swframe->format = AV_PIX_FMT_NV12;
            if (av_hwframe_transfer_data(g_swframe, g_hwframe, 0) < 0) {
                g_errors++;
                av_frame_unref(g_hwframe);
                continue;
            }
            out = g_swframe;
        }
        const uint64_t ts = (uint64_t)g_hwframe->pts;
        keep_frame(out, ts);
        g_decoded++;
        alvr_report_frame_decoded(ts);
        av_frame_unref(g_swframe);
        av_frame_unref(g_hwframe);
    }
    pthread_mutex_unlock(&g_dec_lock);
    return true;
}

static int create_decoder_locked(int codec);

static void free_decoder(void) {
    if (g_dec) avcodec_free_context(&g_dec);
    if (g_hw) av_buffer_unref(&g_hw);
    if (g_hwframe) av_frame_free(&g_hwframe);
    if (g_swframe) av_frame_free(&g_swframe);
    if (g_packet) av_packet_free(&g_packet);
}

/**
 * After ALVR's DecoderConfig event: the decoder for [codec] (0 H.264, 1 HEVC, 2 AV1). 0 when it is ready, 1 when one
 * is already running: ALVR says later DecoderConfig events are to be ignored until a reconnection, and replacing the
 * decoder while ALVR's thread fed it crashed the app (12 Nov 2026).
 */
int pxr_create_decoder(int codec) {
    pthread_mutex_lock(&g_dec_lock);
    if (g_dec) {
        pthread_mutex_unlock(&g_dec_lock);
        return 1;
    }
    int rc = create_decoder_locked(codec);
    pthread_mutex_unlock(&g_dec_lock);
    return rc;
}

static int create_decoder_locked(int codec) {
    free_decoder();
    const enum AVCodecID id = codec == 0 ? AV_CODEC_ID_H264 : codec == 2 ? AV_CODEC_ID_AV1 : AV_CODEC_ID_HEVC;
    const AVCodec *dec = avcodec_find_decoder(id);
    if (!dec) {
        LOG("no decoder for codec %d", codec);
        return -1;
    }
    g_dec = avcodec_alloc_context3(dec);
    g_hw_ok = av_hwdevice_ctx_create(&g_hw, AV_HWDEVICE_TYPE_VAAPI, NULL, NULL, 0) == 0;
    if (g_hw_ok) {
        g_dec->hw_device_ctx = av_buffer_ref(g_hw);
        g_dec->get_format = pick_vaapi;
    } else {
        LOG("VA-API is not available; decoding on the CPU");
    }
    // The stream's parameter sets (VPS/SPS/PPS) come first as extradata, as ALVR gives them.
    const uint64_t size = alvr_get_decoder_config(NULL);
    if (size > 0) {
        g_dec->extradata = av_mallocz(size + AV_INPUT_BUFFER_PADDING_SIZE);
        alvr_get_decoder_config((char *)g_dec->extradata);
        g_dec->extradata_size = (int)size;
    }
    g_dec->flags |= AV_CODEC_FLAG_LOW_DELAY;
    g_dec->flags2 |= AV_CODEC_FLAG2_FAST;
    g_dec->thread_count = 1;
    if (avcodec_open2(g_dec, dec, NULL) < 0) {
        LOG("the decoder would not open");
        free_decoder();
        return -2;
    }
    g_hwframe = av_frame_alloc();
    g_swframe = av_frame_alloc();
    g_packet = av_packet_alloc();
    alvr_set_decoder_input_callback(NULL, decoder_input);
    LOG("decoder: %s, %s, %llu config bytes", dec->name, g_hw_ok ? "on the GPU (VA-API)" : "on the CPU",
        (unsigned long long)size);
    return 0;
}

/** At StreamingStopped (a reconnection gets a new DecoderConfig). */
void pxr_destroy_decoder(void) {
    pthread_mutex_lock(&g_dec_lock);
    free_decoder();
    pthread_mutex_unlock(&g_dec_lock);
}

// ---------------- the session ----------------
/** Starts ALVR: it looks for the PC streamer on the network and keeps the connection up. */
int pxr_init(int view_w, int view_h, float refresh_hz) {
    if (g_initialized) return 0;
    alvr_initialize_logging();
    static float rates[1];
    rates[0] = refresh_hz;
    AlvrClientCapabilities caps;
    memset(&caps, 0, sizeof caps);
    caps.default_view_width = (uint32_t)view_w;
    caps.default_view_height = (uint32_t)view_h;
    caps.max_view_width = (uint32_t)view_w;
    caps.max_view_height = (uint32_t)view_h;
    caps.refresh_rates = rates;
    caps.refresh_rates_count = 1;
    caps.foveated_encoding = false;  // a plain side by side frame the app can sample directly
    caps.encoder_high_profile = true;
    caps.encoder_10_bits = false;
    caps.encoder_av1 = false;
    caps.prefer_10bit = false;
    caps.preferred_encoding_gamma = 1.0f;
    caps.prefer_hdr = false;
    alvr_initialize(caps);
    alvr_resume();
    g_head_id = alvr_path_string_to_id("/user/head");
    g_initialized = 1;
    char host[128] = {0}, proto[64] = {0};
    alvr_hostname(host);
    alvr_protocol_id(proto);
    LOG("ALVR started: %dx%d per eye at %.0f Hz, protocol %s, this Deck shows as %s", view_w, view_h, refresh_hz,
        proto, host);
    return 0;
}

void pxr_destroy(void) {
    if (!g_initialized) return;
    // The decoder goes first: decoder_input() runs on ALVR's thread and calls back into ALVR
    // (alvr_report_frame_decoded), while alvr_destroy() holds ALVR's lock and waits for that thread. Destroying
    // ALVR first froze the app when PC VR was left (12 Nov 2026). Taking g_dec_lock waits for a frame in progress;
    // with no decoder, later frames return at once without calling ALVR.
    pxr_destroy_decoder();
    alvr_pause();
    alvr_destroy();
    g_initialized = 0;
}

/** The next event's tag, or -1 with none; out[4] as Pocket XR's Android bridge fills it. */
int pxr_poll_event(float *out) {
    AlvrEvent e;
    memset(&e, 0, sizeof e);
    if (!alvr_poll_event(&e)) return -1;
    out[0] = out[1] = out[2] = out[3] = 0.0f;
    switch (e.tag) {
        case ALVR_EVENT_STREAMING_STARTED:
            out[0] = (float)e.STREAMING_STARTED.view_width;
            out[1] = (float)e.STREAMING_STARTED.view_height;
            out[2] = e.STREAMING_STARTED.refresh_rate_hint;
            out[3] = e.STREAMING_STARTED.enable_foveated_encoding ? 1.0f : 0.0f;
            break;
        case ALVR_EVENT_HAPTICS:
            out[0] = (float)(e.HAPTICS.device_id & 0xffffffffu);
            out[1] = e.HAPTICS.duration_s;
            out[2] = e.HAPTICS.frequency;
            out[3] = e.HAPTICS.amplitude;
            break;
        case ALVR_EVENT_DECODER_CONFIG:
            out[0] = (float)e.DECODER_CONFIG.codec;
            break;
        default:
            break;
    }
    return (int)e.tag;
}

/** ALVR's lobby text ("Searching for streamer", errors). */
int pxr_hud_message(char *buf, int cap) {
    uint64_t n = alvr_hud_message(NULL);
    if (n + 1 > (uint64_t)cap) return -1;
    alvr_hud_message(buf);
    buf[n] = 0;
    return (int)n;
}

int pxr_hostname(char *buf, int cap) {
    if (cap < 128) return -1;
    memset(buf, 0, 128);
    if (g_initialized) alvr_hostname(buf);
    return 0;
}

uint64_t pxr_now_ns(void) { return now_ns(); }

uint64_t pxr_prediction_offset_ns(void) { return alvr_get_total_prediction_offset_ns(); }

/** Each eye's view in the head: [ipd_m] apart, fovs[8] left, right, up, down radians, left eye first. */
void pxr_send_view_params(float ipd_m, const float *f) {
    AlvrViewParams v[2];
    memset(v, 0, sizeof v);
    for (int e = 0; e < 2; e++) {
        v[e].pose.orientation.w = 1.0f;
        v[e].pose.position[0] = e == 0 ? -ipd_m / 2 : ipd_m / 2;
        v[e].fov.left = f[4 * e];
        v[e].fov.right = f[4 * e + 1];
        v[e].fov.up = f[4 * e + 2];
        v[e].fov.down = f[4 * e + 3];
    }
    alvr_send_view_params(v);
}

/** The head at [target_ns] (pxr_now_ns clock): orientation x y z w, position x y z, angular velocity x y z. */
void pxr_send_head(uint64_t target_ns, const float *h) {
    AlvrDeviceMotion m;
    memset(&m, 0, sizeof m);
    m.device_id = g_head_id;
    m.pose.orientation.x = h[0];
    m.pose.orientation.y = h[1];
    m.pose.orientation.z = h[2];
    m.pose.orientation.w = h[3];
    m.pose.position[0] = h[4];
    m.pose.position[1] = h[5];
    m.pose.position[2] = h[6];
    m.angular_velocity[0] = h[7];
    m.angular_velocity[1] = h[8];
    m.angular_velocity[2] = h[9];
    alvr_send_tracking(target_ns, &m, 1, NULL, NULL);
}

/**
 * GL thread: the newest decoded frame into textures [tex_y] (w x h, one channel) and [tex_uv] (w/2 x h/2, two
 * channels), made or resized here. Returns its timestamp, or 0 with nothing new. out_size[2] gets w, h; out_pose[12]
 * the head orientation the PC drew it with and each eye's fov (left, right, up, down), when ALVR has them.
 */
uint64_t pxr_acquire(unsigned tex_y, unsigned tex_uv, int *out_size, float *out_pose) {
    pthread_mutex_lock(&g_lock);
    if (!g_fresh) {
        pthread_mutex_unlock(&g_lock);
        return 0;
    }
    const uint64_t ts = g_ts;
    const int w = g_w, h = g_h;
    static int tw = 0, th = 0;
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glBindTexture(GL_TEXTURE_2D, tex_y);
    if (tw != w || th != h) {
        glTexImage2D(GL_TEXTURE_2D, 0, GL_LUMINANCE, w, h, 0, GL_LUMINANCE, GL_UNSIGNED_BYTE, g_y);
    } else {
        glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, w, h, GL_LUMINANCE, GL_UNSIGNED_BYTE, g_y);
    }
    glBindTexture(GL_TEXTURE_2D, tex_uv);
    if (tw != w || th != h) {
        glTexImage2D(GL_TEXTURE_2D, 0, GL_LUMINANCE_ALPHA, w / 2, h / 2, 0, GL_LUMINANCE_ALPHA, GL_UNSIGNED_BYTE, g_uv);
    } else {
        glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, w / 2, h / 2, GL_LUMINANCE_ALPHA, GL_UNSIGNED_BYTE, g_uv);
    }
    tw = w;
    th = h;
    g_fresh = 0;
    pthread_mutex_unlock(&g_lock);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 4);
    out_size[0] = w;
    out_size[1] = h;
    AlvrVideoFrameMetadata meta;
    memset(&meta, 0, sizeof meta);
    if (alvr_report_compositor_start(ts, &meta)) {
        const AlvrQuat *r = &meta.view_params[0].pose.orientation;
        const AlvrFov *l = &meta.view_params[0].fov, *g = &meta.view_params[1].fov;
        const float p[12] = {r->x, r->y, r->z, r->w, l->left, l->right, l->up, l->down,
                             g->left, g->right, g->up, g->down};
        memcpy(out_pose, p, sizeof p);
    }
    return ts;
}

/** After the frame [ts] was drawn: [vsync_queue_ns] until it shows, for ALVR's statistics. */
void pxr_submit(uint64_t ts, uint64_t vsync_queue_ns) { alvr_report_submit(ts, vsync_queue_ns); }

/** Decoded frames and errors so far, for the log. */
void pxr_stats(uint64_t *out) {
    out[0] = g_decoded;
    out[1] = g_errors;
    out[2] = (uint64_t)g_hw_ok;
}
