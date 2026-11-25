"""python3 -m pocketxr.host [--ports 47989,48989,49989] [--no-helper] [--seconds S]: the host, as the
pocket-xr-host service runs it, logging to ~/.local/state/pocket-xr-deck/host.log.

Without --ports it serves the PC screens the control panel's "PC screens for a phone" asks for (screens.py: three at
first, up to six), and follows a change within 10 seconds. With --ports it serves those and no others.

python3 -m pocketxr.host --pin NNNN: gives a waiting phone its PIN (when no Pocket XR helper typed it).
"""
import argparse
import os
import signal
import sys
import threading
import time

from . import identity, screens
from .helper import Helper
from .server import Host

STATE = os.path.join(os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")), "pocket-xr-deck")
LOG = os.path.join(STATE, "host.log")


class Log:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > 4 << 20:
            os.replace(path, path + ".1")
        self.f = open(path, "a", encoding="utf-8", buffering=1)
        self.lock = threading.Lock()

    def __call__(self, text):
        line = time.strftime("%H:%M:%S ") + text
        with self.lock:
            self.f.write(line + "\n")
            print(line, flush=True)


def main(argv=None):
    p = argparse.ArgumentParser(prog="pocketxr.host")
    p.add_argument("--ports")
    p.add_argument("--no-helper", action="store_true")
    p.add_argument("--seconds", type=float, default=0)
    p.add_argument("--pin")
    a = p.parse_args(argv)
    if a.pin:
        os.makedirs(identity.FOLDER, exist_ok=True)
        with open(os.path.join(identity.FOLDER, "pin.txt"), "w", encoding="ascii") as f:
            f.write(a.pin.strip())
        return 0
    log = Log(LOG)
    follow = not a.ports
    ports = list(screens.ports(screens.wanted())) if follow else [int(x) for x in a.ports.split(",") if x.strip()]
    host = Host(identity.Identity(log=log), ports=ports, log=log)
    host.start()
    helper = None
    if not a.no_helper:
        helper = Helper(host, log=log)
        try:
            helper.start()
        except OSError as e:
            log("helper: not on %d (%s): is the PC Screens app's helper still running?" % (47610, e))
            helper = None
    done = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: done.set())
    signal.signal(signal.SIGINT, lambda *_: done.set())
    end = time.time() + a.seconds if a.seconds else None
    while not done.wait(10):
        if follow:
            host.set_count(screens.wanted())
        for line in host.stats():
            log("host: " + line)
        if end and time.time() > end:
            break
    log("host: stopping")
    if helper:
        helper.stop()
    host.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
