"""Share layouts and Import layouts: the file Pocket XR on Android reads and writes too, without glasses or a screen."""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pocketxr import i18n  # noqa: E402
from pocketxr import layouts as LY  # noqa: E402
from pocketxr import space as S  # noqa: E402

i18n.set_lang("en")
HERE = os.path.dirname(os.path.abspath(__file__))
ANDROID = os.path.join(HERE, "data", "layouts-android.json")


class App:
    """apps.App's fields, as the app menu gives them."""

    def __init__(self, id_, name, wm_class=""):
        self.id, self.name, self.wm_class = id_, name, wm_class


DECK_APPS = [
    App("org.mozilla.firefox.desktop", "Firefox", "firefox"),
    App("com.google.Chrome.desktop", "Google Chrome", ""),
    App("org.kde.dolphin.desktop", "Dolphin", ""),
    App("steam.desktop", "Steam", "steam"),
    App("org.videolan.VLC.desktop", "VLC media player", "vlc"),
]


def pose(yaw, pitch=0.0, d=1.4, w=40.0, h=22.5, c=0.0):
    return S.Pose(yaw, pitch, d, w, h, c).to_json()


def store(presets=()):
    d = tempfile.mkdtemp()
    s = S.Store(os.path.join(d, "space.json"))
    s.presets = [json.loads(json.dumps(p)) for p in presets]
    return s


def test_round_trip():
    presets = [
        {"name": "Work", "windows": [{"app": "firefox", "pose": pose(10, -5, 1.5, 40, 22.5, 0.0)},
                                     {"app": "Google-chrome", "pose": pose(-40, 3, 2.0, 50, 28, 1.3)}]},
        {"name": "Play", "windows": [{"app": "steam_app_1245620", "pose": pose(0, 0, 3.0, 80, 45, 2.0)}]},
    ]
    seen = ["firefox", "Google-chrome", "steam_app_1245620"]
    apps = LY.local_apps(DECK_APPS, seen)
    data = LY.export(presets, apps, "0.3.0")
    assert data["format"] == "pocket-xr-layouts" and data["version"] == 1 and data["made_by"] == "deck"
    w0 = data["presets"][0]["windows"][0]
    assert w0["app"] == {"name": "Firefox", "android": None, "deck": "firefox"}, w0
    assert data["presets"][0]["windows"][1]["app"]["name"] == "Google Chrome"  # its class is seen, its name the menu's
    assert set(w0) == {"app", "yaw_deg", "pitch_deg", "distance_m", "width_deg", "height_deg", "curve"}
    with tempfile.TemporaryDirectory() as d:
        path = LY.write(os.path.join(d, LY.file_name()), data)
        with open(path, "rb") as f:
            raw = f.read()
        assert b"\r" not in raw and raw.endswith(b"}\n")
        back = LY.read(path)
    s = store()
    merged, added, left_out = LY.merge(s.presets, back, apps)
    assert added == 2 and left_out == []
    assert merged == presets, (merged, presets)


def test_android_file():
    with open(ANDROID, encoding="utf-8") as f:
        data = json.load(f)
    assert data["made_by"] == "android"
    file_presets = LY.check(data, "x.json")
    apps = LY.local_apps(DECK_APPS, [])
    s = store([{"name": "Workspace 1", "windows": [{"app": "firefox", "pose": pose(0)}]}])
    merged, added, left_out = LY.merge(s.presets, file_presets, apps)
    assert added == 1, added  # "Chat" had Messages and Phone only: left out whole
    assert left_out == ["YouTube", "Messages", "Phone"], left_out
    top = merged[0]
    assert top["name"] == "Workspace 1 (2)", top["name"]  # the Deck's own Workspace 1 keeps its name
    assert [w["app"] for w in top["windows"]] == ["firefox", "Chrome"], top  # by name, and Chrome by the alias
    p = S.Pose.from_json(top["windows"][1]["pose"])
    assert (p.yaw, p.pitch, p.distance, p.wdeg, p.hdeg, p.curve) == (45.0, 0.0, 1.4, 36.0, 20.25, 1.2)
    assert merged[1]["name"] == "Workspace 1" and len(merged) == 2
    msg = LY.summary(added, left_out)
    assert msg == "Added 1 layout. 3 windows were left out: YouTube, Messages and Phone aren't on this Deck.", msg


def test_find_order():
    apps = LY.local_apps(DECK_APPS, ["Google-chrome", "org.kde.dolphin"])
    # by the Deck's id first, any case
    assert LY.find({"name": "Something else", "deck": "FIREFOX"}, apps) == "FIREFOX"
    # a Deck id not here falls back on the name
    assert LY.find({"name": "Firefox", "deck": "firefox-esr"}, apps) == "firefox"
    # the name, case and punctuation ignored; a class seen is taken over the menu's guess
    assert LY.find({"name": "google chrome"}, apps) == "Google-chrome"
    assert LY.find({"name": "Chrome"}, apps) == "Google-chrome"
    assert LY.find({"name": "VLC", "android": "org.videolan.vlc"}, apps) == "vlc"
    assert LY.find({"name": "dolphin"}, apps) == "org.kde.dolphin"
    # phone-only apps are not swapped for anything
    for n in ("YouTube", "Messages", "Phone", "Files", ""):
        assert LY.find({"name": n, "android": "x.y"}, apps) is None, n
    assert LY.find(None, apps) is None


def test_version_check():
    ok = {"format": "pocket-xr-layouts", "version": 1, "presets": []}
    assert LY.check(ok) == []
    newer = dict(ok, version=2)
    try:
        LY.check(newer, "f.json")
        raise AssertionError("a newer version was read")
    except LY.LayoutsError as e:
        assert "newer Pocket XR" in str(e) and "Update Pocket XR" in str(e) and "f.json" in str(e), str(e)
    for bad in (dict(ok, format="something-else"), dict(ok, version="1"), dict(ok, version=True), dict(ok, version=0),
                {"format": "pocket-xr-layouts", "presets": []}, dict(ok, presets={}), [], "x"):
        try:
            LY.check(bad, "f.json")
            raise AssertionError(f"read {bad!r}")
        except LY.LayoutsError as e:
            assert "not a Pocket XR layouts file" in str(e), str(e)
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "pocketxr-layouts-x.json")
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write("{ not json")
        try:
            LY.read(p)
            raise AssertionError("read bad JSON")
        except LY.LayoutsError as e:
            assert "pocketxr-layouts-x.json" in str(e)


def test_limit_of_eight():
    own = [{"name": f"Mine {i}", "windows": [{"app": "firefox", "pose": pose(i)}]} for i in range(7)]  # newest first
    file_presets = [{"name": n, "windows": [{"app": {"name": "Firefox"}, "yaw_deg": 0, "pitch_deg": 0,
                                             "distance_m": 1.4, "width_deg": 40, "height_deg": 22.5, "curve": 0}]}
                    for n in ("A", "Mine 0", "Mine 0")]
    apps = LY.local_apps(DECK_APPS, [])
    merged, added, left_out = LY.merge(own, file_presets, apps)
    assert len(merged) == S.PRESETS_MAX == 8
    assert [p["name"] for p in merged] == ["A", "Mine 0 (2)", "Mine 0 (3)", "Mine 0", "Mine 1", "Mine 2", "Mine 3",
                                          "Mine 4"], [p["name"] for p in merged]
    assert added == 3 and left_out == []
    many = file_presets * 4  # 12 in the file: 8 kept
    merged, added, _ = LY.merge([], many, apps)
    assert len(merged) == 8 and added == 8
    assert LY.summary(8, []) == "Added 8 layouts."


def test_values_kept_in_the_decks_limits():
    w = {"app": {"name": "Firefox"}, "yaw_deg": 270.0, "pitch_deg": 120, "distance_m": 99, "width_deg": "wide",
         "height_deg": 1.0, "curve": 9}
    p = LY.pose_of(w)
    assert p.yaw == -90.0 and p.pitch == S.MAX_PITCH and p.distance == S.MAX_DISTANCE
    assert p.wdeg == S.DEFAULT_WIDTH_DEG and p.hdeg == S.DEPTH_MIN_SIZE_DEG
    assert 0 < p.curve <= min(S.CURVE_MAX, S.max_curve(p.wdeg))


def test_buttons_with_downloads():
    with tempfile.TemporaryDirectory() as home:
        s = store([{"name": "Work", "windows": [{"app": "firefox", "pose": pose(5)}]}])
        apps = LY.local_apps(DECK_APPS, ["firefox"])
        assert LY.import_newest(s, apps, home=home)[0] == ""  # no Downloads yet
        assert LY.share(store(), apps, "0.3.0", home=home) is None  # nothing to share
        now = time.mktime((2026, 11, 13, 12, 0, 0, 0, 0, -1))
        path = LY.share(s, apps, "0.3.0", home=home, now=now)
        assert os.path.basename(path) == "pocketxr-layouts-2026-11-13.json", path
        # an older file and a newer one from the phone, saved by a browser with its own suffix
        with open(ANDROID, encoding="utf-8") as f:
            android = f.read()
        phone = os.path.join(home, "Downloads", "pocketxr-layouts-2026-11-12 (1).json")
        with open(phone, "w", encoding="utf-8", newline="\n") as f:
            f.write(android)
        os.utime(path, (now - 100, now - 100))
        os.utime(phone, (now, now))
        took, msg = LY.import_newest(s, apps, home=home)
        assert took == "Took pocketxr-layouts-2026-11-12 (1).json from Downloads.", took
        assert msg.startswith("Added 1 layout. "), msg
        assert [p["name"] for p in s.presets] == ["Workspace 1", "Work"]
        with open(s.path, encoding="utf-8") as f:
            assert [p["name"] for p in json.load(f)["presets"]] == ["Workspace 1", "Work"]  # saved
        # a file from a newer Pocket XR changes nothing
        with open(phone, "w", encoding="utf-8", newline="\n") as f:
            f.write(android.replace('"version": 1', '"version": 2'))
        os.utime(phone, (now, now))
        took, msg = LY.import_newest(s, apps, home=home)
        assert "newer Pocket XR" in msg and len(s.presets) == 2, (took, msg, len(s.presets))


def test_summary_words():
    assert LY.summary(0, []) == "No layouts were added."
    assert LY.summary(3, ["Messages", "Phone"]) == \
        "Added 3 layouts. 2 windows were left out: Messages and Phone aren't on this Deck."
    assert LY.summary(2, ["Messages"]) == "Added 2 layouts. 1 window was left out: Messages isn't on this Deck."
    assert LY.summary(2, ["Messages", "Messages"]) == \
        "Added 2 layouts. 2 windows were left out: Messages isn't on this Deck."


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
