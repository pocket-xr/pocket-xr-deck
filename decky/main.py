"""Pocket XR's Quick Access panel, backend: a bridge to Pocket XR's Gaming Mode service (pocketxr/gaming.py), which
listens on a socket in the user's runtime folder for one JSON request per line."""
import asyncio
import json
import os
import socket

import decky


def _socket_path():
    # The service runs as the Deck's user; this backend may not, so the user's id comes from their home folder.
    uid = os.stat(decky.DECKY_USER_HOME).st_uid
    return f"/run/user/{uid}/pocket-xr-gaming.sock"


def _ask(req):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(30.0 if req.get("op") == "send_logs" else 1.5)  # making the logs' zip takes a few seconds
    try:
        s.connect(_socket_path())
        f = s.makefile("rw")
        f.write(json.dumps(req) + "\n")
        f.flush()
        answer = json.loads(f.readline())
        answer["running"] = True
        return answer
    except (OSError, ValueError) as e:
        return {"running": False, "why": str(e)}
    finally:
        s.close()


class Plugin:
    async def request(self, req: dict) -> dict:
        return await asyncio.get_event_loop().run_in_executor(None, _ask, req)

    async def _main(self):
        decky.logger.info("Pocket XR panel ready")

    async def _unload(self):
        pass
