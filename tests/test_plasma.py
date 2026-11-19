import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from osu_cursor import gnome, plasma
from osu_cursor.skin import SkinError
from test_skin import png


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    if sys.platform != "linux":
        pytest.skip("Plasma integration runs on Linux")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(gnome, "screen_size", lambda: (1920, 1080))
    monkeypatch.setattr(plasma, "effect_status", lambda: "unavailable")
    settings = ["breeze_cursors", 36]
    monkeypatch.setattr(plasma, "cursor_settings", lambda: tuple(settings))

    def apply_theme(theme, size):
        settings[:] = [theme, size]

    monkeypatch.setattr(plasma, "apply_theme", apply_theme)
    skin = tmp_path / "test"
    skin.mkdir()
    (skin / "cursor.png").write_bytes(png())
    (skin / "cursortrail.png").write_bytes(png())
    return skin, settings


def test_apply_and_reset_restore_theme_and_size(desktop):
    skin, settings = desktop
    assert gnome.apply_skin(skin).has_trail
    theme = settings[0]
    assert plasma.THEME_PATTERN.fullmatch(theme)
    state = gnome.data_dir() / "plasma" / "state.json"
    assert json.loads(state.read_text())["theme"] == theme
    assert not (gnome.data_dir() / "state.json").exists()
    gnome.set_trail_enabled(False)
    assert not json.loads(state.read_text())["trail_enabled"]
    gnome.set_cursor_size(1.5)
    assert settings[0] != theme
    settings[1] = 48
    assert gnome.reset() == "breeze_cursors"
    assert settings == ["breeze_cursors", 36]
    assert gnome.current_skin() is None


def test_failed_apply_keeps_previous_skin_and_settings(desktop, monkeypatch):
    skin, settings = desktop
    gnome.apply_skin(skin)
    current = settings[:]
    directory = gnome.data_dir() / "plasma"
    before = [(directory / name).read_bytes() for name in ("previous.json", "state.json")]

    def fail(theme, size):
        raise SkinError("apply failed")

    monkeypatch.setattr(plasma, "apply_theme", fail)
    with pytest.raises(SkinError, match="apply failed"):
        gnome.apply_skin(skin, 1.7)
    assert settings == current
    assert [(directory / name).read_bytes() for name in ("previous.json", "state.json")] == before
    assert gnome.cursor_size() == 1.0


def test_reset_keeps_a_theme_selected_outside_the_app(desktop):
    skin, settings = desktop
    gnome.apply_skin(skin)
    settings[:] = ["Breeze_Light", 42]
    assert gnome.reset() is None
    assert settings == ["Breeze_Light", 42]
    assert gnome.current_skin() is None


def test_removing_applied_skin_restores_plasma(desktop):
    skin, settings = desktop
    gnome.add_skin(skin)
    stored = gnome.library_skins()[0]
    gnome.apply_skin(stored.path)
    gnome.remove_skin(stored.path)
    assert settings == ["breeze_cursors", 36]
    assert not stored.path.exists()


def test_missing_trail_state_is_reported_without_reverting_theme(desktop):
    skin, settings = desktop
    gnome.apply_skin(skin)
    state = gnome.data_dir() / "plasma" / "state.json"
    state.unlink()
    assert gnome.trail_problem() == "The Plasma trail data could not be loaded."
    assert plasma.THEME_PATTERN.fullmatch(settings[0])


@pytest.mark.parametrize("code,configured,success", [(0, "skin", True), (255, "skin", True),
                                                    (255, "original", False), (1, "skin", False)])
def test_apply_theme_interprets_plasma_exit_status(monkeypatch, code, configured, success):
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("XDG_DATA_HOME", "/example/data")
    monkeypatch.setenv("XCURSOR_PATH", "/existing/icons")
    monkeypatch.setattr(plasma, "_relogin", False)
    monkeypatch.setattr(plasma, "cursor_settings", lambda: (configured, 24))

    def run(*args, check, env):
        assert args == ("plasma-apply-cursortheme", "--size", "24", "--", "skin")
        assert env["XCURSOR_PATH"].split(os.pathsep) == [str(Path("/example/data") / "icons"), "/existing/icons"]
        return subprocess.CompletedProcess(args, code)

    monkeypatch.setattr(plasma, "_run", run)
    if success:
        plasma.apply_theme("skin", 24)
        assert bool(plasma.notice()) == (code == 255)
    else:
        with pytest.raises(SkinError, match="Could not apply"):
            plasma.apply_theme("skin", 24)


def test_screen_uses_active_primary_scale_and_rotation(monkeypatch):
    primary = {
        "enabled": True, "connected": True, "priority": 1, "rotation": 2, "scale": 1.25,
        "currentModeId": "1", "modes": [{"id": "1", "size": {"width": 2560, "height": 1440}}],
    }
    outputs = [{**primary, "priority": 2, "rotation": 1}, primary,
               {**primary, "enabled": False, "priority": 1}]
    monkeypatch.setattr(plasma, "_run", lambda *args: subprocess.CompletedProcess(
        args, 0, stdout=json.dumps({"outputs": outputs})))
    assert plasma.screen_size() == (1152, 2048)


@pytest.mark.parametrize("status,expected", [(0, ["new", 36]), (2, ["old", 48])])
def test_apply_theme_persists_size_or_restores_settings(monkeypatch, status, expected):
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setattr(plasma, "_relogin", False)
    settings = ["old", 48]
    monkeypatch.setattr(plasma, "cursor_settings", lambda: tuple(settings))

    def run(*args, check=True, env=None):
        if args[0] == "kwriteconfig6":
            key, value = args[-2:]
            if key == "cursorSize":
                settings[1] = int(value)
            else:
                assert key == "cursorTheme"
                settings[0] = value
            return subprocess.CompletedProcess(args, 0)
        assert args[0] == "plasma-apply-cursortheme"
        assert settings[1] == 36
        settings[0] = "new"
        return subprocess.CompletedProcess(args, status)

    monkeypatch.setattr(plasma, "_run", run)
    if status:
        with pytest.raises(SkinError, match="Could not apply"):
            plasma.apply_theme("new", 36)
    else:
        plasma.apply_theme("new", 36)
    assert settings == expected
