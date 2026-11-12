"""SDL2 and fixed-function OpenGL through ctypes. Both come with SteamOS, so nothing is installed."""
import ctypes
import ctypes.util

sdl = ctypes.CDLL(ctypes.util.find_library("SDL2-2.0") or "libSDL2-2.0.so.0")
gl = ctypes.CDLL(ctypes.util.find_library("GL") or "libGL.so.1")


class Rect(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int), ("w", ctypes.c_int), ("h", ctypes.c_int)]


SDL_INIT_VIDEO = 0x20
SDL_WINDOW_OPENGL = 0x2
SDL_WINDOW_BORDERLESS = 0x10
SDL_WINDOW_FULLSCREEN_DESKTOP = 0x1001
SDL_WINDOW_ALWAYS_ON_TOP = 0x8000
SDL_WINDOW_SKIP_TASKBAR = 0x10000
SDL_QUIT = 0x100
SDL_KEYDOWN = 0x300
SDL_MOUSEBUTTONDOWN = 0x401
SDL_GL_DOUBLEBUFFER = 5
KMOD_CTRL = 0x00C0

sdl.SDL_GetDisplayName.restype = ctypes.c_char_p
sdl.SDL_GetError.restype = ctypes.c_char_p
sdl.SDL_CreateWindow.restype = ctypes.c_void_p
sdl.SDL_CreateWindow.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint32]
sdl.SDL_GL_CreateContext.restype = ctypes.c_void_p
sdl.SDL_GL_CreateContext.argtypes = [ctypes.c_void_p]
sdl.SDL_GL_DeleteContext.argtypes = [ctypes.c_void_p]
sdl.SDL_GL_SwapWindow.argtypes = [ctypes.c_void_p]
sdl.SDL_GL_GetDrawableSize.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
sdl.SDL_DestroyWindow.argtypes = [ctypes.c_void_p]
sdl.SDL_ShowCursor.argtypes = [ctypes.c_int]
sdl.SDL_SetHint.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
sdl.SDL_GetWindowDisplayIndex.argtypes = [ctypes.c_void_p]
sdl.SDL_InitSubSystem.argtypes = [ctypes.c_uint32]
sdl.SDL_QuitSubSystem.argtypes = [ctypes.c_uint32]

GL_COLOR_BUFFER_BIT = 0x4000
GL_PROJECTION = 0x1701
GL_MODELVIEW = 0x1700
GL_TEXTURE_2D = 0x0DE1
GL_RGBA = 0x1908
GL_BGRA = 0x80E1
GL_UNSIGNED_BYTE = 0x1401
GL_LINEAR = 0x2601
GL_TEXTURE_MIN_FILTER = 0x2801
GL_TEXTURE_MAG_FILTER = 0x2800
GL_TEXTURE_WRAP_S = 0x2802
GL_TEXTURE_WRAP_T = 0x2803
GL_CLAMP_TO_EDGE = 0x812F
GL_QUADS = 0x0007
GL_LINE_LOOP = 0x0002
GL_TRIANGLE_FAN = 0x0006
GL_BLEND = 0x0BE2
GL_SRC_ALPHA = 0x0302
GL_ONE_MINUS_SRC_ALPHA = 0x0303
GL_UNPACK_ALIGNMENT = 0x0CF5

for _n, _k in (("glClearColor", 4), ("glTexCoord2f", 2), ("glVertex3f", 3), ("glColor3f", 3), ("glColor4f", 4),
               ("glTranslatef", 3), ("glRotatef", 4), ("glLineWidth", 1)):
    getattr(gl, _n).argtypes = [ctypes.c_float] * _k
gl.glFrustum.argtypes = [ctypes.c_double] * 6
gl.glTexImage2D.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                            ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
gl.glTexSubImage2D.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                               ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
gl.glMultMatrixf.argtypes = [ctypes.POINTER(ctypes.c_float)]
gl.glDeleteTextures.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint)]


def displays():
    """[(index, name, x, y, w, h)] as SDL sees them now."""
    out = []
    for i in range(sdl.SDL_GetNumVideoDisplays()):
        r = Rect()
        sdl.SDL_GetDisplayBounds(i, ctypes.byref(r))
        name = (sdl.SDL_GetDisplayName(i) or b"?").decode(errors="replace")
        out.append((i, name, r.x, r.y, r.w, r.h))
    return out


GLASSES_NAMES = ("xreal", "ultra", "viture", "nreal", "air", "rokid", "rayneo")


def split_displays(found):
    """(the glasses' display, the Deck's own) from SDL's list; either may be None."""
    deck = None
    glasses = None
    for d in found:
        n = d[1].lower()
        if any(k in n for k in GLASSES_NAMES):
            glasses = d
        elif "anx7530" in n or (d[2] == 0 and d[3] == 0 and deck is None):
            deck = deck or d
    if glasses is None:
        others = [d for d in found if d is not deck]
        glasses = others[0] if others else None
    return glasses, deck
