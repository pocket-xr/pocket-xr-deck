"""PC VR proof on the Deck, without drawing: find the Pocket XR PC helper, pair once (the PC asks its user), ask it to
start SteamVR for this Deck's ALVR name, run ALVR's client through Pocket XR's bridge, and count decoded frames.

  python3 tools/pcvr_probe.py [seconds]
"""
import ctypes
import json
import math
import os
import socket
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
NATIVE = os.path.join(HERE, "..", "native", "out")
STATE = os.path.expanduser("~/.config/pocket-xr-deck/pc-helper.json")
PORT = 47610

lib = ctypes.CDLL(os.path.join(NATIVE, "libpxr_pcvr.so"))
lib.pxr_init.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_float]
lib.pxr_poll_event.argtypes = [ctypes.POINTER(ctypes.c_float)]
lib.pxr_hud_message.argtypes = [ctypes.c_char_p, ctypes.c_int]
lib.pxr_hostname.argtypes = [ctypes.c_char_p, ctypes.c_int]
lib.pxr_now_ns.restype = ctypes.c_uint64
lib.pxr_prediction_offset_ns.restype = ctypes.c_uint64
lib.pxr_send_view_params.argtypes = [ctypes.c_float, ctypes.POINTER(ctypes.c_float)]
lib.pxr_send_head.argtypes = [ctypes.c_uint64, ctypes.POINTER(ctypes.c_float)]
lib.pxr_stats.argtypes = [ctypes.POINTER(ctypes.c_uint64)]


def log(m):
    print(time.strftime("%H:%M:%S ") + m, flush=True)


def find_helper(timeout=4.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(0.5)
    end = time.time() + timeout
    while time.time() < end:
        s.sendto(b"POCKETXR-FIND 1", ("255.255.255.255", PORT))
        try:
            data, addr = s.recvfrom(256)
        except socket.timeout:
            continue
        parts = data.decode().split()
        if parts[:2] == ["POCKETXR-HERE", "1"]:
            return addr[0], int(parts[2]), " ".join(parts[3:])
    return None


def ask(host, port, req, timeout=60.0):
    with socket.create_connection((host, port), timeout=timeout) as c:
        c.sendall((json.dumps(req) + "\n").encode())
        f = c.makefile()
        return json.loads(f.readline())


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 60
    found = find_helper()
    if not found:
        log("no Pocket XR PC helper answered on the network")
        return 1
    host, port, pc = found
    log(f"PC helper on {pc} ({host}:{port})")
    try:
        token = json.load(open(STATE)).get("token")
    except (OSError, ValueError):
        token = None
    if not token:
        log("pairing: approve 'Steam Deck' on the PC")
        r = ask(host, port, {"op": "pair", "phone": "Steam Deck"}, timeout=120)
        if not r.get("ok"):
            log(f"not paired: {r}")
            return 1
        token = r["token"]
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        json.dump({"token": token, "pc": r.get("pc")}, open(STATE, "w"))
        log("paired")

    # ALVR's client: 1920 x 1080 per eye at 60, the Aura's 3D mode.
    lib.pxr_init(1920, 1080, 60.0)
    name = ctypes.create_string_buffer(128)
    lib.pxr_hostname(name, 128)
    alvr_name = name.value.decode()
    log(f"this Deck is {alvr_name} to ALVR")
    r = ask(host, port, {"op": "start", "token": token, "alvr": alvr_name})
    log(f"start: {r}")

    # The glasses' view: about 63 x 38 degrees per eye.
    h, v = math.atan(math.tan(math.radians(19)) * 16 / 9), math.radians(19)
    fovs = (ctypes.c_float * 8)(-h, h, v, -v, -h, h, v, -v)
    ev = (ctypes.c_float * 4)()
    head = (ctypes.c_float * 10)(0, 0, 0, 1, 0, 1.6, 0, 0, 0, 0)
    stats = (ctypes.c_uint64 * 3)()
    hud_last = ""
    end = time.time() + seconds
    last_status = 0.0
    tags = {0: "HUD", 1: "STREAMING_STARTED", 2: "STREAMING_STOPPED", 3: "HAPTICS", 4: "DECODER_CONFIG", 5: "REALTIME"}
    while time.time() < end:
        while True:
            t = lib.pxr_poll_event(ev)
            if t < 0:
                break
            log(f"event {tags.get(t, t)} {list(ev)}")
            if t == 1:
                lib.pxr_send_view_params(0.063, fovs)
            elif t == 4:
                rc = lib.pxr_create_decoder(int(ev[0]))
                log(f"decoder: {rc}")
            elif t == 2:
                lib.pxr_destroy_decoder()
        hud = ctypes.create_string_buffer(4096)
        lib.pxr_hud_message(hud, 4096)
        if hud.value.decode(errors="replace") != hud_last:
            hud_last = hud.value.decode(errors="replace")
            log("hud: " + hud_last.replace("\n", " | "))
        now = lib.pxr_now_ns()
        lib.pxr_send_head(now + lib.pxr_prediction_offset_ns(), head)
        if time.time() - last_status > 3:
            last_status = time.time()
            lib.pxr_stats(stats)
            log(f"decoded {stats[0]} frames, {stats[1]} errors, gpu decode {bool(stats[2])}")
        time.sleep(1 / 60)
    lib.pxr_destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
