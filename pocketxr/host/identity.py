"""The host's identity and its paired phones, in ~/.config/pocket-xr-deck/host/ (this user only):

  cert.pem, key.pem   a self-signed RSA 2048 certificate, as Sunshine makes (made with SteamOS's openssl), shared by
                      every PC screen, so a phone paired once is paired with all of them
  ids.json            {"<port>": "<unique id>"}: one id per PC screen, as the phone saves each screen as its own computer
  clients.json        [{"name", "id", "cert" (PEM), "paired"}]: the phones' certificates, pinned

The first start takes over what the Pocket XR PC Screens app (patched Sunshine, ~/.config/pocketxr) had: its
certificate, key, ids and paired phones, so a phone paired with it needs no pairing again.
"""
import json
import os
import subprocess
import threading
import time
import uuid

from . import rsa

FOLDER = os.environ.get("PXR_HOST_CONFIG") or os.path.join(os.path.expanduser("~/.config/pocket-xr-deck"), "host")
OLD = os.path.expanduser("~/.config/pocketxr")  # the PC Screens app's (Sunshine) settings
OLD_BASE_PORT = 47989
OLD_SCREENS = 3  # the PC Screens app had three Sunshines: sunshine-1 to sunshine-3


def _write(path, text, private=False):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    if private:
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _old_state(old, port):
    path = os.path.join(old, "sunshine-%d" % ((port - OLD_BASE_PORT) // 1000 + 1), "sunshine_state.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("root", {})
    except (OSError, ValueError, AttributeError):
        return {}


class Identity:
    def __init__(self, folder=FOLDER, old=OLD, log=print):
        self.folder = folder
        self.old = old
        self.log = log
        self.lock = threading.Lock()
        os.makedirs(folder, mode=0o700, exist_ok=True)
        self.cert_path = os.path.join(folder, "cert.pem")
        self.key_path = os.path.join(folder, "key.pem")
        if not (os.path.exists(self.cert_path) and os.path.exists(self.key_path)):
            self._make_or_take()
        with open(self.cert_path, encoding="ascii") as f:
            self.cert_pem = f.read()
        with open(self.key_path, encoding="ascii") as f:
            self.key = rsa.private_key(f.read())
        self.cert_der = rsa.pem_blocks(self.cert_pem)[0][1]
        self.cert_signature = rsa.cert_signature(self.cert_der)
        self.ids_path = os.path.join(folder, "ids.json")
        self.clients_path = os.path.join(folder, "clients.json")
        self.clients = self._load(self.clients_path, [])
        if not os.path.exists(self.clients_path):
            self._take_old_clients()

    @staticmethod
    def _load(path, default):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return default

    def _make_or_take(self):
        cert, key = os.path.join(self.old, "sunshine-cert.pem"), os.path.join(self.old, "sunshine-key.pem")
        if os.path.exists(cert) and os.path.exists(key):
            with open(cert, encoding="ascii") as f:
                c = f.read()
            with open(key, encoding="ascii") as f:
                k = f.read()
            _write(self.cert_path, c)
            _write(self.key_path, k, private=True)
            self.log("host: took the PC Screens app's certificate, so its paired phones stay paired")
            return
        r = subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256", "-nodes", "-days", "7300",
                            "-subj", "/CN=Sunshine Gamestream Host", "-keyout", self.key_path, "-out", self.cert_path],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise OSError("openssl could not make the host's certificate: " + r.stderr.strip()[-200:])
        os.chmod(self.key_path, 0o600)
        self.log("host: made this Deck's host certificate")

    def _take_old_clients(self):
        taken = []
        for n in range(OLD_SCREENS):
            for d in _old_state(self.old, OLD_BASE_PORT + 1000 * n).get("named_devices", []):
                if isinstance(d, dict) and d.get("cert") and all(c["cert"] != d["cert"] for c in taken):
                    taken.append({"name": d.get("name") or "Phone", "id": d.get("uuid") or str(uuid.uuid4()).upper(),
                                  "cert": d["cert"], "paired": time.strftime("%Y-%m-%d %H:%M")})
        self.clients = taken
        self._save_clients()
        if taken:
            self.log("host: took %d paired phone(s) from the PC Screens app" % len(taken))

    def unique_id(self, port):
        """This PC screen's id: kept, taken from the PC Screens app's Sunshine on the same port, or new."""
        with self.lock:
            ids = self._load(self.ids_path, {})
            if str(port) not in ids:
                ids[str(port)] = _old_state(self.old, port).get("uniqueid") or str(uuid.uuid4()).upper()
                _write(self.ids_path, json.dumps(ids, indent=1))
            return ids[str(port)]

    def sign(self, data):
        return rsa.sign(self.key, data)

    # ---- paired phones ----

    def _save_clients(self):
        _write(self.clients_path, json.dumps(self.clients, indent=1), private=True)

    def knows(self, der):
        if not der:
            return False
        pem = rsa.der_to_pem(der)
        with self.lock:
            return any(_same_pem(c["cert"], pem) for c in self.clients)

    def add(self, name, client_id, der):
        pem = rsa.der_to_pem(der)
        with self.lock:
            # One record per certificate: a phone paired again replaces its old record.
            self.clients = [c for c in self.clients if not _same_pem(c["cert"], pem)]
            self.clients.append({"name": name, "id": client_id, "cert": pem, "paired": time.strftime("%Y-%m-%d %H:%M")})
            self._save_clients()

    def count(self):
        with self.lock:
            return len(self.clients)


def _same_pem(a, b):
    try:
        return rsa.pem_blocks(a)[0][1] == rsa.pem_blocks(b)[0][1]
    except (IndexError, ValueError):
        return False
