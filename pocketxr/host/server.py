"""Pocket XR on the Steam Deck as the PC end of the phone's PC screens, with no Sunshine: the host that Moonlight's
protocol reaches (ported from Sunshine and Apollo, GPLv3, as Pocket XR for Windows' PcHost).

Three PC screens at first, up to six (screens.py), each its own computer to the phone, on its own base port P (47989,
48989, 49989, as the PC Screens app's Sunshines were, then 50989, 51989, 52989): HTTP P, HTTPS P-5, video P+9, control
P+10, sound P+11, RTSP P+21. Each stream gets a KWin virtual output at the phone's window shape.
"""
import hashlib
import os
import re
import secrets
import socket
import threading
import time
import urllib.parse
from xml.sax.saxutils import escape

from . import audio, control, desktop, ossl, rsa, screens, video
from .. import readability
from .inputs import Inputs

APP_ID = 1
BASE_PORTS = screens.ports(screens.DEFAULT)  # 47989, 48989, 49989
# Apollo's permission bits as the PC helper gives a phone (input, clipboard both ways, launch, view), and what the
# phone checks before it streams.
PERMISSION = 0x07031F00 | 0x4001800


def xml(code, message, inner):
    msg = ' status_message="%s"' % escape(message, {'"': "&quot;"}) if message else ""
    return '<?xml version="1.0" encoding="utf-8"?><root status_code="%d"%s>%s</root>' % (code, msg, inner)


def el(tag, value):
    return "<%s>%s</%s>" % (tag, escape(str(value)), tag)


def query(target):
    q = {}
    if "?" in target:
        for k, v in urllib.parse.parse_qsl(target.split("?", 1)[1], keep_blank_values=True):
            q[k.lower()] = v
    return q


def read_request(recv):
    """(method, target, headers text, body) from a connection's recv(n), or None."""
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = recv(65536)
        if not chunk:
            return None
        data += chunk
        if len(data) > 1 << 20:
            return None
    head, body = data.split(b"\r\n\r\n", 1)
    head = head.decode("latin-1")
    m = re.search(r"(?im)^content-length:\s*(\d+)", head)
    length = int(m.group(1)) if m else 0
    while len(body) < length:
        chunk = recv(65536)
        if not chunk:
            break
        body += chunk
    first = head.split("\r\n", 1)[0].split(" ")
    if len(first) < 2:
        return None
    return first[0], first[1], head, body[:length]


def sdp_int(body, key):
    m = re.search(re.escape(key) + r":\s*(-?\d+)", body)
    return int(m.group(1)) if m else None


class PinBox:
    """The PIN of the phone pairing now: from the PC helper on this Deck (as it types it into Apollo), or
    python3 -m pocketxr.host --pin NNNN (the pin file)."""

    def __init__(self, pin_file):
        self.pin_file = pin_file
        self.cond = threading.Condition()
        self.wanted = False
        self.pin = None
        self.name = None

    def wait(self, seconds):
        with self.cond:
            self.wanted, self.pin, self.name = True, None, None
        try:
            os.remove(self.pin_file)
        except OSError:
            pass
        end = time.time() + seconds
        try:
            while time.time() < end:
                with self.cond:
                    if self.pin:
                        return self.pin
                    self.cond.wait(0.25)
                try:
                    with open(self.pin_file, encoding="ascii") as f:
                        pin = f.read().strip()
                    os.remove(self.pin_file)
                    if re.fullmatch(r"\d{4}", pin):
                        return pin
                except OSError:
                    pass
            return None
        finally:
            with self.cond:
                self.wanted = False

    def submit(self, pin, name=None):
        with self.cond:
            if not self.wanted or not re.fullmatch(r"\d{4}", pin or ""):
                return False
            self.pin, self.name = pin, name
            self.cond.notify_all()
            return True


class Session:
    def __init__(self):
        self.width = self.height = 0
        self.fps = 60
        self.key = b""
        self.key_id = 0
        self.ping_payload = secrets.token_hex(8).upper()
        self.connect_data = secrets.randbelow(2 ** 31)
        self.packet_size, self.kbps, self.min_fec = 1392, 20000, 2
        self.codec = "h264"
        self.audio_ms = 5
        self.audio_encrypted = True
        self.local_audio = False
        self.video = self.control = self.audio = self.sink = None
        self.output = None
        self.area = None
        self.started = 0.0
        self.stopped = False
        self.lock = threading.Lock()


def serve(port, handler, log, bind="0.0.0.0", name="host"):
    """A TCP server on [port], each connection handled on its own thread."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((bind, port))
    srv.listen(16)

    def accept():
        while True:
            try:
                conn, peer = srv.accept()
            except OSError:
                return
            threading.Thread(target=handler, args=(conn, peer), daemon=True, name=name).start()

    threading.Thread(target=accept, daemon=True, name=name + "-accept").start()
    return srv


class Screen:
    """One PC screen: a computer of its own to the phone."""

    def __init__(self, host, index, port):
        self.host = host
        self.index = index
        self.http_port, self.https_port = port, port - 5
        self.video_port, self.control_port, self.audio_port, self.rtsp_port = port + 9, port + 10, port + 11, port + 21
        self.name = host.name if index == 0 else "%s screen %d" % (host.name, index + 1)
        self.unique_id = host.identity.unique_id(port)
        self.session = None
        self.lock = threading.Lock()
        self.servers = []
        self.pairings = {}
        self.mdns = None

    @property
    def log(self):
        return self.host.log

    def start(self):
        self.servers = []
        for port, handler, name in ((self.http_port, lambda c, p: self._web(c, p, False), "host-http"),
                                    (self.https_port, lambda c, p: self._web(c, p, True), "host-https"),
                                    (self.rtsp_port, self._rtsp, "host-rtsp")):
            self.servers.append(serve(port, handler, self.log, name=name))
        threading.Thread(target=self._announce, daemon=True).start()

    def _announce(self):
        self.mdns = desktop.Announcement(self.name, self.http_port, self.log)

    def stop(self):
        self.end("the host stopped")
        for s in self.servers:
            try:
                s.close()
            except OSError:
                pass
        if self.mdns:
            self.mdns.close()

    @property
    def running(self):
        with self.lock:
            return self.session is not None

    # ---- the web side ----

    def _web(self, conn, peer, secure):
        tls = None
        try:
            conn.settimeout(150)  # pairing's first step waits for the PIN
            cert = None
            if secure:
                tls = self.host.tls.wrap(conn)
                cert = tls.peer_certificate()
                recv, send = tls.recv, tls.sendall
            else:
                recv, send = conn.recv, conn.sendall
            req = read_request(recv)
            if req is None:
                return
            method, target, _, body = req
            local = conn.getsockname()[0]
            paired = secure and self.host.identity.knows(cert)
            path = target.split("?", 1)[0]
            status, ctype = 200, "application/xml"
            try:
                if path == "/actions/clipboard":
                    status, text = self._clipboard(method, body, paired)
                    ctype = "text/plain; charset=utf-8"
                else:
                    text = self.handle(target, secure, paired, cert, local, peer[0])
            except Exception as e:  # one request's failure, answered
                self.log("host: %s failed: %s" % (path, e))
                text = xml(400, str(e), "")
            if not text and ctype == "application/xml":
                status, text = 404, xml(404, "Not Found", "")
            data = text.encode("utf-8")
            reason = {200: "OK", 401: "Unauthorized", 403: "Forbidden"}.get(status, "Not Found")
            send(("HTTP/1.1 %d %s\r\nContent-Type: %s\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" %
                  (status, reason, ctype, len(data))).encode("ascii") + data)
        except OSError:
            pass  # a client that went away mid-request, or a failed handshake
        finally:
            if tls:
                tls.close()
            try:
                conn.close()
            except OSError:
                pass

    def _clipboard(self, method, body, paired):
        """Apollo's clipboard request, text only, for a paired phone with a stream running."""
        if not paired:
            return 401, ""
        if not self.running:
            return 403, ""
        if method == "POST":
            text = body.decode("utf-8", "replace")
            ok = desktop.clipboard_set(text)
            self.log("host: clipboard from the phone, %d characters%s" % (len(text), "" if ok else ": not set"))
            return (200 if ok else 403), ""
        got = desktop.clipboard_get()
        return 200, got or ""

    def handle(self, target, secure, paired, cert, local, remote):
        path = target.split("?", 1)[0].strip("/")
        q = query(target)
        if path != "serverinfo":
            self.log("host: %s /%s from %s%s" % ("HTTPS" if secure else "HTTP", path, remote,
                                                 (" (paired)" if paired else " (not paired)") if secure else ""))
        if path == "serverinfo":
            return self.serverinfo(secure and paired, local)
        if path == "pair":
            return self.pair(q, secure, paired)
        if path == "unpair":
            return xml(200, "", "")
        if not paired:
            return xml(401, "The client is not authorized. Certificate verification failed.", "")
        if path == "applist":
            return xml(200, "", "<App><IsHdrSupported>0</IsHdrSupported><AppTitle>Desktop</AppTitle><UUID></UUID>"
                                "<ID>%d</ID></App>" % APP_ID)
        if path in ("launch", "resume"):
            url = self.launch(q, local, path == "resume")
            tag = "gamesession" if path == "launch" else "resume"
            if url is None:
                return xml(200, "", el(tag, 0))
            return xml(200, "", el("sessionUrl0", url) + el(tag, 1))
        if path == "cancel":
            self.end("the phone ended it")
            return xml(200, "", el("cancel", 1))
        return ""

    def serverinfo(self, paired, local):
        h = self.host
        running = paired and self.running
        parts = [el("hostname", self.name), el("appversion", "7.1.431.-1"), el("GfeVersion", "3.23.0.74"),
                 el("uniqueid", self.unique_id), el("HttpsPort", self.https_port), el("ExternalPort", self.http_port),
                 el("MaxLumaPixelsHEVC", "1869449984" if "hevc" in h.codecs else "0"), el("mac", "00:00:00:00:00:00"),
                 el("Permission", PERMISSION if paired else 0)]
        if paired:
            parts += [el("VirtualDisplayCapable", "true"), el("VirtualDisplayDriverReady", "true")]
        parts += [el("LocalIP", local), el("ServerCodecModeSupport", h.codec_support), el("PairStatus", 1 if paired else 0),
                  el("currentgame", APP_ID if running else 0), el("currentgameuuid", ""),
                  el("state", "SUNSHINE_SERVER_BUSY" if running else "SUNSHINE_SERVER_FREE")]
        return xml(200, "", "".join(parts))

    # ---- pairing (Apollo's nvhttp.cpp getservercert ... clientpairingsecret) ----

    def _fail(self, cid, why):
        self.pairings.pop(cid, None)
        self.log("host: pairing failed: %s" % why)
        return xml(400, why, el("paired", 0))

    def pair(self, q, secure, paired):
        cid = q.get("uniqueid", "")
        phrase = q.get("phrase")
        if phrase == "pairchallenge":
            return xml(200, "", el("paired", 1 if secure and paired else 0))
        if phrase == "getservercert":
            salt = q.get("salt", "")
            if len(salt) < 32:
                return self._fail(cid, "Salt too short")
            try:
                blocks = rsa.pem_blocks(bytes.fromhex(q.get("clientcert", "")))
                der = blocks[0][1]
                rsa.cert_signature(der)
            except (ValueError, IndexError):
                return self._fail(cid, "Invalid client certificate")
            name = q.get("devicename") or "Phone"
            self.log("host: %s (%s) asks to pair with %s: waiting for its PIN" % (name, cid, self.name))
            pin = self.host.pins.wait(120)
            if pin is None:
                return self._fail(cid, "No PIN was given")
            self.pairings[cid] = {"phase": 1, "aes": hashlib.sha256(bytes.fromhex(salt[:32]) + pin.encode()).digest()[:16],
                                  "cert": der, "name": self.host.pins.name or name}
            return xml(200, "", el("paired", 1) + el("plaincert", self.host.identity.cert_pem.encode().hex().upper()))
        s = self.pairings.get(cid)
        if s is None:
            return self._fail(cid, "Out of order pairing call")
        ident = self.host.identity
        if "clientchallenge" in q:
            if s["phase"] != 1:
                return self._fail(cid, "Out of order call to clientchallenge")
            s["phase"] = 2
            dec = ossl.aes_ecb(s["aes"], bytes.fromhex(q["clientchallenge"]), False)
            s["secret"] = secrets.token_bytes(16)
            digest = hashlib.sha256(dec + ident.cert_signature + s["secret"]).digest()
            s["challenge"] = secrets.token_bytes(16)
            enc = ossl.aes_ecb(s["aes"], digest + s["challenge"], True)
            return xml(200, "", el("paired", 1) + el("challengeresponse", enc.hex().upper()))
        if "serverchallengeresp" in q:
            if s["phase"] != 2:
                return self._fail(cid, "Out of order call to serverchallengeresp")
            s["phase"] = 3
            s["client_hash"] = ossl.aes_ecb(s["aes"], bytes.fromhex(q["serverchallengeresp"]), False)
            secret = s["secret"] + ident.sign(s["secret"])
            return xml(200, "", el("pairingsecret", secret.hex().upper()) + el("paired", 1))
        if "clientpairingsecret" in q:
            if s["phase"] != 3:
                return self._fail(cid, "Out of order call to clientpairingsecret")
            data = bytes.fromhex(q["clientpairingsecret"])
            if len(data) <= 16:
                return self._fail(cid, "Client pairing secret too short")
            secret, signature = data[:16], data[16:]
            digest = hashlib.sha256(s["challenge"] + rsa.cert_signature(s["cert"]) + secret).digest()
            same = digest == s["client_hash"][:32]
            signed = rsa.verify(s["cert"], secret, signature)
            self.pairings.pop(cid, None)
            if not (same and signed):
                self.log("host: pairing refused (same hash %s, signature %s): a wrong PIN?" % (same, signed))
                return xml(200, "", el("paired", 0))
            ident.add(s["name"], cid, s["cert"])
            self.log("host: paired with %s (%s)" % (s["name"], cid))
            return xml(200, "", el("paired", 1))
        return self._fail(cid, "Unknown pairing step")

    # ---- launch ----

    def launch(self, q, local, resume):
        m = re.fullmatch(r"(\d+)x(\d+)x(\d+)", q.get("mode", ""))
        key = q.get("rikey", "")
        try:
            key_id = int(q.get("rikeyid", ""))
        except ValueError:
            key_id = None
        if not m or len(key) != 32 or key_id is None:
            self.log("host: launch refused: no mode, rikey or rikeyid")
            return None
        if not self.host.codecs:
            self.log("host: launch refused: no encoder (is this Desktop Mode?)")
            return None
        with self.lock:
            if self.session is not None and not resume:
                self._stop(self.session, "a new launch")
                self.session = None
            s = self.session or Session()
            s.width, s.height, s.fps = int(m.group(1)), int(m.group(2)), max(1, int(m.group(3)))
            s.key = bytes.fromhex(key)
            s.key_id = key_id & 0xFFFFFFFF
            s.local_audio = q.get("localaudioplaymode") == "1"
            self.session = s
        self.log("host: %s %dx%d@%d on %s, virtual display asked %s" % (
            "resume" if resume else "launch", s.width, s.height, s.fps, self.name, q.get("virtualdisplay", "0")))
        return "rtsp://%s:%d" % (local, self.rtsp_port)

    def end(self, why):
        with self.lock:
            s, self.session = self.session, None
        if s is not None:
            self._stop(s, why)

    def _stop(self, s, why):
        self.log("host: %s: session ended (%s)" % (self.name, why))
        with s.lock:
            s.stopped = True
            if s.control:
                s.control.terminate()
                time.sleep(0.1)
            for part in (s.video, s.audio, s.control):
                if part:
                    try:
                        part.close()
                    except Exception as e:
                        self.log("host: closing: %s" % e)
            if s.sink:
                s.sink.close()
            s.video = s.audio = s.control = s.sink = None
        threading.Thread(target=self.host.layout.refresh, kwargs={"place": True}, daemon=True).start()

    # ---- RTSP (Sunshine's rtsp.cpp) ----

    def _rtsp(self, conn, peer):
        try:
            conn.settimeout(10)
            req = read_request(conn.recv)
            if req is None:
                return
            verb, target, head, body = req
            cseq = "0"
            m = re.search(r"(?im)^cseq:\s*(\S+)", head)
            if m:
                cseq = m.group(1)
            options, payload, status = self.rtsp(verb, target, body.decode("utf-8", "replace"))
            text = "RTSP/1.0 %d %s\r\nCSeq: %s\r\n" % (status, "OK" if status == 200 else "NOT FOUND", cseq)
            text += "".join("%s: %s\r\n" % kv for kv in options)
            if payload:
                text += "Content-length: %d\r\n" % len(payload.encode("utf-8"))
            text += "\r\n" + payload
            conn.sendall(text.encode("utf-8"))
            conn.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        finally:
            conn.close()

    def rtsp(self, verb, target, body):
        with self.lock:
            s = self.session
        self.log("host: RTSP %s %s" % (verb, target))
        if verb == "OPTIONS":
            return [], "", 200
        if verb == "DESCRIBE":
            # HEVC offered when this Deck encodes it; control encryption V2 and sound encryption (1 | 4), no video
            # encryption, as Sunshine. (The Deck's chip has no AV1 encoder.)
            sdp = ("sprop-parameter-sets=AAAAAU\n" if "hevc" in self.host.codecs else "") + \
                  ("a=rtpmap:98 AV1/90000\n" if "av1" in self.host.codecs else "") + \
                  "a=x-ss-general.featureFlags:0\na=x-ss-general.encryptionSupported:5\n" \
                  "a=x-ss-general.encryptionRequested:1\n"
            return [], sdp, 200
        if s is None:
            return [], "", 404
        if verb == "SETUP":
            m = re.search(r"streamid=(\w+)", target)
            kind = m.group(1) if m else ""
            port = {"audio": self.audio_port, "video": self.video_port, "control": self.control_port}.get(kind)
            if not port:
                return [], "", 404
            options = [("Session", "DEADBEEFCAFE;timeout = 90"), ("Transport", "server_port=%d" % port)]
            if kind == "control":
                options.append(("X-SS-Connect-Data", str(s.connect_data)))
            else:
                options.append(("X-SS-Ping-Payload", s.ping_payload))
            return options, "", 200
        if verb == "ANNOUNCE":
            self.announce(s, body)
            return [], "", 200
        if verb == "PLAY":
            self.begin(s)
            return [], "", 200
        return [], "", 404

    def announce(self, s, body):
        s.width = sdp_int(body, "x-nv-video[0].clientViewportWd") or s.width
        s.height = sdp_int(body, "x-nv-video[0].clientViewportHt") or s.height
        s.fps = sdp_int(body, "x-nv-video[0].maxFPS") or s.fps
        s.packet_size = sdp_int(body, "x-nv-video[0].packetSize") or s.packet_size
        s.kbps = sdp_int(body, "x-nv-vqos[0].bw.maximumBitrateKbps") or s.kbps
        mf = sdp_int(body, "x-nv-vqos[0].fec.minRequiredFecPackets")
        s.min_fec = s.min_fec if mf is None else mf
        enc = sdp_int(body, "x-ss-general.encryptionEnabled") or 0
        s.audio_ms = sdp_int(body, "x-nv-aqos.packetDuration") or 5
        # Sound is encrypted when the client says so either way (Sunshine's rtsp.cpp: nv feature flag 0x20).
        s.audio_encrypted = bool(enc & 4) or bool((sdp_int(body, "x-nv-general.featureFlags") or 0) & 0x20)
        fmt = sdp_int(body, "x-nv-vqos[0].bitStreamFormat") or 0
        s.codec = {1: "hevc", 2: "av1"}.get(fmt, "h264")
        if s.codec not in self.host.codecs:
            s.codec = "h264"
        self.log("host: ANNOUNCE %dx%d@%d, %d Mbps, packets %d, FEC minimum %d, encryption %d, %s" % (
            s.width, s.height, s.fps, s.kbps // 1000, s.packet_size, s.min_fec, enc, s.codec))

    def begin(self, s):
        """PLAY: the control and sound ports open now, and PLAY is answered at once; the picture (the virtual output,
        capture and encoder) starts on its own, so the phone connects its streams meanwhile."""
        with s.lock:
            if s.video or s.stopped:
                return
            s.started = time.time()
            h = self.host
            try:
                s.control = control.Control(self.control_port, s.key, self.log,
                                            on_input=lambda payload: h.inputs.handle(payload, s.area or h.layout.desktop()),
                                            on_idr=lambda: s.video and s.video.idr(),
                                            on_gone=lambda: self._gone(s))
            except OSError as e:
                self.log("host: %s" % e)
                return
            if s.local_audio:
                monitor = "@DEFAULT_SINK@.monitor"
            else:
                s.sink = desktop.Sink(self.http_port, "Pocket XR: " + self.name, self.log)
                monitor = s.sink.monitor()
            try:
                s.audio = audio.Audio(self.audio_port, s.key, s.key_id, s.audio_encrypted, s.audio_ms, monitor, self.log)
                s.audio.start()
            except OSError as e:
                self.log("host: no sound: %s" % e)
            output = "pxr-%d" % self.http_port
            args = video.command(s.width, s.height, s.fps, s.kbps, s.codec, self.video_port, s.packet_size, s.min_fec,
                                 output, "Pocket XR: " + self.name)
            s.video = video.Video(args, self.log, on_output=lambda name: self._placed(s, name),
                                  on_client=lambda: s.area and h.inputs.centre(s.area),
                                  on_end=lambda code: self._video_ended(s, code))

    def _placed(self, s, name):
        desktop.close_display_switch(self.log)
        layout = self.host.layout
        self._scale(s, name)
        layout.refresh(place=True)
        s.output = name
        s.area = layout.area(name)
        self.log("host: %s is %s at %s, %.2f s after PLAY" % (self.name, name, s.area, time.time() - s.started))
        if s.area:
            self.host.inputs.centre(s.area)

    def _scale(self, s, name):
        """Readability or Text size (readability.py, as Pocket XR for Mac): KWin's scale on this PC screen's output,
        from the desktop app's settings when the screen is made, and the log says what it was made at."""
        on, text = readability.desktop_choice()
        scale = readability.host_scale(s.width, on, text)
        # Set at Standard (1) too: KWin remembers an output's scale by its name, so a PC screen made again after a
        # change back to Standard would otherwise keep the old one.
        err = desktop.set_scale(name, scale)
        if err:
            self.log("host: %s (%s) made at %dx%d; scale %g not set (%s)" % (self.name, name, s.width, s.height,
                                                                               scale, err))
        else:
            self.log(readability.host_line(self.name, name, s.width, s.height, on, text, scale))

    def _gone(self, s):
        with self.lock:
            mine = self.session is s
        if mine:
            self.end("the phone went")

    def _video_ended(self, s, code):
        with self.lock:
            mine = self.session is s and not s.stopped
        if mine:
            self.end("the picture stopped (%s)" % code)


class Host:
    def __init__(self, identity, ports=BASE_PORTS, name=None, log=print, codecs=None, pin_file=None):
        self.log = log
        self.identity = identity
        self.name = name or socket.gethostname().split(".")[0]
        self.codecs = codecs if codecs is not None else video.probe(log)
        self.codec_support = 0x1 | (0x100 if "hevc" in self.codecs else 0) | (0x10000 if "av1" in self.codecs else 0)
        self.tls = ossl.TlsServerContext(identity.cert_path, identity.key_path)
        self.pins = PinBox(pin_file or os.path.join(identity.folder, "pin.txt"))
        self.layout = desktop.Layout(log)
        self.inputs = Inputs(log, desktop=self.layout.desktop)
        self.screens = [Screen(self, i, p) for i, p in enumerate(ports)]
        self.busy = set()  # base ports another program held: not tried again
        self.change = threading.Lock()

    @property
    def ports(self):
        return [s.http_port for s in self.screens]

    def start(self):
        ready, busy = [], set()
        for s in self.screens:
            try:
                s.start()
                ready.append(s)
            except OSError as e:
                # Another streaming host (an earlier Sunshine) holds this screen's ports: the others still serve,
                # and the helper lists only these.
                self.log("host: %s not served, port %d busy (%s)" % (s.name, s.http_port, e))
                busy.add(s.http_port)
                s.stop()
        self.screens = ready
        self.busy = busy
        self.inputs.start()
        self.log("host: %s ready on %s (%d paired, %s)" % (
            self.name, ", ".join(str(p) for p in self.ports), self.identity.count(),
            ", ".join(c.upper() for c in self.codecs) or "no encoder"))

    def set_count(self, count):
        """Serves PC screens 1 to [count] (screens.py) from now on, as the control panel's "PC screens for a phone" asks.
        New ones start at once. One past [count] stops once no phone streams from it, so a stream is never cut: the
        next call stops it. A port found busy is left out and not tried again. True when the screens changed."""
        want = screens.ports(count)
        with self.change:
            have = {s.http_port for s in self.screens}
            keep, changed = [], False
            for s in self.screens:
                if s.http_port in want or s.running:
                    keep.append(s)
                else:
                    s.stop()
                    changed = True
            for i, port in enumerate(want):
                if port in have or port in self.busy:
                    continue
                s = Screen(self, i, port)
                try:
                    s.start()
                except OSError as e:
                    self.log("host: %s not served, port %d busy (%s)" % (s.name, port, e))
                    self.busy.add(port)
                    s.stop()
                    continue
                keep.append(s)
                changed = True
            if changed:
                self.screens = sorted(keep, key=lambda s: s.http_port)
                self.log("host: %s now on %s (%d PC screens asked for)" % (
                    self.name, ", ".join(str(p) for p in self.ports), len(want)))
            return changed

    def stop(self):
        for s in self.screens:
            s.stop()
        self.inputs.close()

    def stats(self):
        """One line on each running stream, for the log."""
        out = []
        for sc in self.screens:
            with sc.lock:
                s = sc.session
            if s and s.control:
                out.append("%s: control %s, %d inputs, %d sound packets" % (
                    sc.name, "connected" if s.control.connected else "not connected", s.control.inputs,
                    s.audio.sent if s.audio else 0))
        return out
