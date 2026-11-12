"""Saves what the glasses show (the X screen right of the Deck's) to a PNG: python3 shot_glasses.py out.png [x w h]."""
import ctypes
import os
import sys

sys.path.insert(0, os.path.expanduser("~/.local/share/pocket-xr-deck"))
from pocketxr import xcapture as X, text as T  # noqa: E402

out = sys.argv[1]
x, w, h = (int(a) for a in sys.argv[2:5]) if len(sys.argv) > 4 else (1280, 1920, 1080)
d = X.x11.XOpenDisplay(None)
r = X.x11.XDefaultRootWindow(d)
img = X.x11.XGetImage(d, r, x, 0, w, h, 0xFFFFFFFF, 2)
data = ctypes.c_void_p.from_address(img + 16).value
c = T.cairo
c.cairo_image_surface_create_for_data.restype = ctypes.c_void_p
c.cairo_image_surface_create_for_data.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
c.cairo_surface_write_to_png.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
c.cairo_surface_write_to_png(c.cairo_image_surface_create_for_data(data, 1, w, h, w * 4), out.encode())
