import json
import string
import subprocess
import sys

import pytest

from messages import ROOT, all_messages
from osu_cursor import i18n


def fields(text: str) -> list[str]:
    return sorted(field for _literal, field, _spec, _conversion in string.Formatter().parse(text) if field)


@pytest.mark.parametrize("code", sorted(i18n.LANGUAGES))
def test_every_message_is_translated(code):
    catalog = json.loads((i18n.LOCALE_DIR / f"{code}.json").read_text(encoding="utf-8"))
    messages = all_messages()
    assert sorted(messages - catalog.keys()) == [], "missing translations"
    assert sorted(catalog.keys() - messages) == [], "translations of text the app no longer shows"
    for english, translated in catalog.items():
        assert translated.strip(), english
        assert fields(translated) == fields(english), english
        assert translated.count("\n") == english.count("\n"), english


def test_every_locale_file_is_listed():
    assert sorted(path.stem for path in i18n.LOCALE_DIR.glob("*.json")) == sorted(i18n.LANGUAGES)


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        ([], None),
        (["C"], None),
        (["en_US.UTF-8"], None),
        (["tr_TR.UTF-8"], "tr"),
        (["de_AT.UTF-8"], "de"),
        (["pt_PT.UTF-8"], "pt_BR"),
        (["pt"], "pt_BR"),
        (["zh_CN.UTF-8"], "zh_CN"),
        (["zh_TW.UTF-8"], None),  # traditional script, simplified would be wrong
        (["sr_RS@latin"], None),
        (["nl", "fr", "de"], "fr"),  # the first one we have
        (["ru_RU.UTF-8@euro"], "ru"),
    ],
)
def test_language_is_picked_like_gettext(requested, expected):
    assert i18n.pick_language(requested) == expected


def test_language_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("LANGUAGE", "")
    monkeypatch.setenv("LC_ALL", "")
    monkeypatch.setenv("LC_MESSAGES", "ja_JP.UTF-8")
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    assert i18n._requested() == ["ja_JP.UTF-8"]
    monkeypatch.setenv("LANGUAGE", "pl:en")
    assert i18n._requested() == ["pl", "en"]


def test_shell_scripts_print_translated_messages():
    done = subprocess.run(
        [sys.executable, "-m", "osu_cursor.i18n", "Unknown option: {option}", "option=--x"],
        cwd=ROOT,
        env={"LANGUAGE": "tr", "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert done.stdout == "Bilinmeyen seçenek: --x\n"
