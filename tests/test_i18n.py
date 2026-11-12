"""Checks for the translations: every text the code marks has a translation in every language, with the same
placeholders, and the language is found from Steam's name for it, the locale or our own setting."""
import ast
import glob
import json
import os
import string
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from pocketxr import i18n  # noqa: E402


def marked_texts():
    """Every English text the code passes to tr() or N_() as a literal."""
    keys = set()
    for path in glob.glob(os.path.join(ROOT, "pocketxr", "*.py")):
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and node.args:
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                arg = node.args[0]
                if name in ("tr", "N_") and isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    keys.add(arg.value)
    return keys


def fields(s):
    return sorted(f for _, f, _, _ in string.Formatter().parse(s) if f is not None)


def locales():
    out = {}
    for code in i18n.LANGS:
        if code == "en":
            continue
        with open(os.path.join(i18n.LOCALE_DIR, code + ".json"), encoding="utf-8") as f:
            out[code] = json.load(f)
    return out


def test_code_marks_texts():
    keys = marked_texts()
    assert len(keys) > 150, len(keys)
    assert "Control Center" in keys and "Workspace {n}" in keys and "Circle" in keys


def test_every_locale_has_every_text():
    keys = marked_texts()
    for code, table in locales().items():
        missing = sorted(keys - set(table))
        extra = sorted(set(table) - keys)
        assert not missing, (code, missing)
        assert not extra, (code, extra)
        empty = [k for k, v in table.items() if not isinstance(v, str) or not v.strip()]
        assert not empty, (code, empty)


def test_placeholders_match():
    for code, table in locales().items():
        for k, v in table.items():
            assert fields(k) == fields(v), (code, k, v)
            v.format(**{f: "x" for f in fields(k)})  # and it formats


def test_no_em_dashes_in_english():
    assert not [k for k in marked_texts() if "\u2014" in k]


def test_steam_names():
    expect = {"english": "en", "koreana": "ko", "japanese": "ja", "schinese": "zh_CN", "tchinese": "zh_TW",
              "spanish": "es", "latam": "es", "brazilian": "pt_BR", "portuguese": "pt_BR", "french": "fr",
              "german": "de", "italian": "it", "russian": "ru"}
    for steam, code in expect.items():
        assert i18n.normalize(steam) == code, (steam, i18n.normalize(steam))
    assert i18n.normalize("polish") is None  # not ours yet: the locale is asked next


def test_locale_names():
    assert i18n.normalize("ko_KR.UTF-8") == "ko"
    assert i18n.normalize("zh_TW.UTF-8") == "zh_TW"
    assert i18n.normalize("zh_HK") == "zh_TW"
    assert i18n.normalize("zh-Hant") == "zh_TW"
    assert i18n.normalize("zh_CN.UTF-8") == "zh_CN"
    assert i18n.normalize("pt_PT.UTF-8") == "pt_BR"
    assert i18n.normalize("de_DE@euro") == "de"
    assert i18n.normalize("C.UTF-8") is None and i18n.normalize("POSIX") is None and i18n.normalize("") is None


REGISTRY = '''"Registry"
{
	"HKCU"
	{
		"Software"
		{
			"Valve"
			{
				"Steam"
				{
					"RunningAppID"		"0"
					"steamglobal"
					{
						"language"		"english"
					}
					"language"		"%s"
					"SourceModInstallPath"		"/home/deck/.local/share/Steam/steamapps\\\\sourcemods"
				}
			}
		}
	}
}
'''


def test_detect_order():
    with tempfile.TemporaryDirectory() as d:
        reg = os.path.join(d, "registry.vdf")
        with open(reg, "w", encoding="utf-8", newline="\n") as f:
            f.write(REGISTRY % "koreana")
        assert i18n.steam_language(reg) == "koreana"
        assert i18n.detect({}, reg) == "ko"
        assert i18n.detect({"LANG": "fr_FR.UTF-8"}, reg) == "ko"  # Steam's language before the locale
        assert i18n.detect({"POCKET_XR_LANG": "ja"}, reg) == "ja"  # ours before Steam's
        assert i18n.detect({"POCKET_XR_LANG": "tchinese"}, reg) == "zh_TW"
        missing = os.path.join(d, "none.vdf")
        assert i18n.detect({"LANG": "de_DE.UTF-8"}, missing) == "de"
        assert i18n.detect({"LC_ALL": "ru_RU.UTF-8", "LANG": "de_DE.UTF-8"}, missing) == "ru"
        assert i18n.detect({"LANG": "C"}, missing) == "en"
        assert i18n.detect({}, missing) == "en"


def test_tr_falls_back_to_english():
    try:
        i18n.set_lang("ko")
        assert i18n.tr("Control Center") != "Control Center"
        assert i18n.tr("A text nobody translated") == "A text nobody translated"
        assert "7" in i18n.tr("Workspace {n}", n=7)
        i18n.set_lang("en")
        assert i18n.tr("Opening {app}", app="Firefox") == "Opening Firefox"
    finally:
        i18n.set_lang(i18n.detect())


def test_cjk_fonts():
    try:
        from pocketxr import text
    except OSError:
        return  # no Cairo here
    assert text.plain_font("ko") == "Noto Sans CJK KR"
    assert text.ui_font(lang="ja") == "Noto Sans CJK JP"
    assert text.ui_font(True, lang="zh_TW") == "Noto Sans CJK TC Medium"
    assert text.ui_font(lang="zh_CN") == "Noto Sans CJK SC"
    assert text.ui_font(lang="ru") == "Inter" and text.plain_font("fr") == "Noto Sans"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
