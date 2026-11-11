"""Translations of the text shown to the user.

The English text is written in the code and wrapped in _(). Other languages come
from locale/<code>.json, which maps each English text to its translation. The
language follows the desktop's, the same way gettext picks it.

Messages with a number are worded like "Skins added: {count}" so that no
language needs plural forms.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

LOCALE_DIR = Path(__file__).with_name("locale")
# Languages with a file in locale/, by the code used for the file.
LANGUAGES = {
    "tr": "Türkçe",
    "es": "Español",
    "pt_BR": "Português (Brasil)",
    "de": "Deutsch",
    "fr": "Français",
    "ru": "Русский",
    "pl": "Polski",
    "ja": "日本語",
    "zh_CN": "简体中文",
}
# Used when only the language is given, or a region has no file of its own.
REGION_FALLBACKS = {"pt": "pt_BR", "zh": "zh_CN"}
TRADITIONAL_CHINESE = {"zh_TW", "zh_HK", "zh_MO"}  # simplified script would be wrong for these


def _requested() -> list[str]:
    """The languages asked for in the environment, most wanted first."""
    for variable in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(variable)
        if value:
            # LANGUAGE may list several, the others hold one.
            return value.split(":") if variable == "LANGUAGE" else [value]
    return []


def pick_language(requested: list[str]) -> str | None:
    """The code of the first requested language we have, or None for English."""
    for entry in requested:
        code = entry.split(".")[0].split("@")[0]
        if code in ("", "C", "POSIX") or code.startswith("en"):
            return None
        if code in LANGUAGES:
            return code
        if code in TRADITIONAL_CHINESE:
            continue
        language = code.split("_")[0]
        if language in LANGUAGES:
            return language
        if language in REGION_FALLBACKS:
            return REGION_FALLBACKS[language]
    return None


def _load(code: str | None) -> dict[str, str]:
    if code is None:
        return {}
    try:
        catalog = json.loads((LOCALE_DIR / f"{code}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {key: value for key, value in catalog.items() if isinstance(value, str) and value}


LANGUAGE = pick_language(_requested())
_catalog = _load(LANGUAGE)


def _(text: str) -> str:
    """The text in the user's language, or the English text if there is no translation."""
    return _catalog.get(text, text)


if __name__ == "__main__":
    # For the shell scripts: python3 -m osu_cursor.i18n "Text {name}" name=value
    message = _(sys.argv[1])
    values = dict(argument.split("=", 1) for argument in sys.argv[2:])
    print(message.format(**values) if values else message)
