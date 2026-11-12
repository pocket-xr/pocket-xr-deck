"""Pocket XR in the user's language: tr("English text") gives that text in the user's language, keyed by the English.

The language, first found wins:
  1. POCKET_XR_LANG (a code like ko or zh_TW, or a Steam name like koreana);
  2. Steam's own UI language, from ~/.steam/registry.vdf (HKCU/Software/Valve/Steam/language, e.g. "koreana");
  3. LC_ALL, LC_MESSAGES, LANG;
  4. English.
Translations are in locale/<code>.json, one object from the English to the translation. A text missing there is shown
in English. Placeholders are str.format fields with names, the same in every language: tr("Opening {app}", app=name).
"""
import json
import os
import re

LANGS = ("en", "ko", "ja", "zh_CN", "zh_TW", "es", "pt_BR", "fr", "de", "it", "ru")

# Steam's language names (the "language" key Steam keeps in registry.vdf) to ours.
STEAM = {
    "english": "en", "koreana": "ko", "korean": "ko", "japanese": "ja", "schinese": "zh_CN", "tchinese": "zh_TW",
    "spanish": "es", "latam": "es", "brazilian": "pt_BR", "portuguese": "pt_BR", "french": "fr", "german": "de",
    "italian": "it", "russian": "ru",
}

REGISTRY = os.path.expanduser("~/.steam/registry.vdf")
LOCALE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locale")

_lang = None
_table = None


def normalize(code):
    """Our code for a locale or Steam name ("ko_KR.UTF-8", "zh-Hant", "koreana", "pt"), or None if we have none."""
    if not code:
        return None
    c = code.strip()
    if c.lower() in STEAM:
        return STEAM[c.lower()]
    c = c.split(".")[0].split("@")[0].replace("-", "_")
    if not c or c in ("C", "POSIX"):
        return None
    parts = c.split("_")
    base = parts[0].lower()
    rest = [p.lower() for p in parts[1:]]
    if base == "zh":
        return "zh_TW" if any(p in ("tw", "hk", "mo", "hant") for p in rest) else "zh_CN"
    if base == "pt":
        return "pt_BR"
    return base if base in LANGS else None


def _vdf(text):
    """A Valve KeyValues text as nested dicts, keys in lower case."""
    root = {}
    stack = [root]
    key = None
    for m in re.finditer(r'"((?:[^"\\]|\\.)*)"|([{}])', text):
        s, brace = m.group(1), m.group(2)
        if brace == "{":
            d = {}
            if key is not None:
                stack[-1][key.lower()] = d
            stack.append(d)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        elif key is None:
            key = s
        else:
            stack[-1][key.lower()] = s
            key = None
    return root


def steam_language(path=REGISTRY):
    """Steam's UI language name ("english", "koreana", ...) from its registry.vdf, or None."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            reg = _vdf(f.read())
    except OSError:
        return None
    steam = reg.get("registry", {}).get("hkcu", {}).get("software", {}).get("valve", {}).get("steam", {})
    lang = steam.get("language") if isinstance(steam, dict) else None
    if not isinstance(lang, str) and isinstance(steam, dict):
        lang = (steam.get("steamglobal") or {}).get("language")
    return lang if isinstance(lang, str) and lang else None


def detect(env=None, registry=REGISTRY):
    """The user's language code, one of LANGS."""
    env = os.environ if env is None else env
    for code in (env.get("POCKET_XR_LANG"), steam_language(registry),
                 env.get("LC_ALL"), env.get("LC_MESSAGES"), env.get("LANG")):
        lang = normalize(code)
        if lang:
            return lang
    return "en"


def lang():
    global _lang
    if _lang is None:
        _lang = detect()
    return _lang


def load(code):
    """The translations for a language code, {} for English or when its file cannot be read."""
    if code == "en":
        return {}
    try:
        with open(os.path.join(LOCALE_DIR, code + ".json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def set_lang(code):
    """Use this language from now on (tests, and anything that wants another)."""
    global _lang, _table
    _lang = normalize(code) or "en"
    _table = load(_lang)


def N_(english):
    """Marks English kept as a key and translated later with tr(), such as layout names (tests find every mark)."""
    return english


def tr(english, **fmt):
    global _table
    if _table is None:
        _table = load(lang())
    text = _table.get(english) or english
    if not fmt:
        return text
    try:
        return text.format(**fmt)
    except (KeyError, IndexError, ValueError):
        return english.format(**fmt)
