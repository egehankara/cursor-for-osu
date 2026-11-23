"""Plasma 6 Wayland tools for cursor settings, screen size and effect status."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
from pathlib import Path

from .i18n import _
from .skin import SkinError

THEME_PREFIX = "osu-cursor-plasma-"
THEME_PATTERN = re.compile(r"^osu-cursor-plasma-[0-9a-f]{12}$")
DEFAULT_THEME = "default"
DEFAULT_SIZE = 24
EFFECT_ID = "osu-cursor-trail"
_relogin = False


def selected() -> bool:
    desktop = os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("XDG_SESSION_DESKTOP", "")
    return bool({"kde", "plasma", "plasmawayland"} & set(desktop.lower().split(":")))


def require_wayland() -> None:
    if os.environ.get("XDG_SESSION_TYPE") != "wayland":
        raise SkinError(_("Plasma support requires a Wayland session."))


def _run(*args: str, check: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=check, capture_output=True, text=True, timeout=10, env=env)


def cursor_settings() -> tuple[str, int]:
    try:
        theme = _run("kreadconfig6", "--file", "kcminputrc", "--group", "Mouse",
                     "--key", "cursorTheme", "--default", DEFAULT_THEME).stdout.strip()
        size = int(_run("kreadconfig6", "--file", "kcminputrc", "--group", "Mouse",
                        "--key", "cursorSize", "--default", str(DEFAULT_SIZE)).stdout.strip())
        return theme or DEFAULT_THEME, max(0, size)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        raise SkinError(_("Could not read Plasma cursor settings.")) from error


def _write_setting(key: str, value: str) -> None:
    _run("kwriteconfig6", "--file", "kcminputrc", "--group", "Mouse", "--key", key, value)


def _theme_command_environment() -> dict[str, str]:
    data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    inherited = os.environ.get("XCURSOR_PATH") or os.pathsep.join(
        ["~/.icons", *(str(Path(directory) / "icons") for directory in data_dirs.split(os.pathsep)),
         "/usr/share/pixmaps"]
    )
    # The Plasma command searches libXcursor's paths, which can omit XDG_DATA_HOME.
    return {**os.environ, "XCURSOR_PATH": f"{Path(data_home) / 'icons'}{os.pathsep}{inherited}"}


def apply_theme(theme: str, size: int) -> None:
    """Apply through Plasma and distinguish its relogin warning from failure."""
    global _relogin
    require_wayland()
    old_theme, old_size = cursor_settings()
    args = ("--size", str(size)) if size else ()
    error_message = _("Could not apply the Plasma cursor theme. Check your Plasma installation.")
    try:
        if size != old_size:
            _write_setting("cursorSize", str(size))
        if theme == DEFAULT_THEME:
            # Plasma's theme chooser can omit the default alias from its model.
            _write_setting("cursorTheme", "--delete")
            _run("gdbus", "emit", "--session", "--object-path", "/KGlobalSettings",
                 "--signal", "org.kde.KGlobalSettings.notifyChange", "5", "0")
            _relogin = False
            return
        done = _run("plasma-apply-cursortheme", *args, "--", theme, check=False,
                    env=_theme_command_environment())
        if done.returncode in (0, 255) and cursor_settings() == (theme, size):
            _relogin = done.returncode == 255
            return
        raise SkinError(error_message)
    except (OSError, subprocess.SubprocessError, SkinError) as error:
        try:
            configured_theme, configured_size = cursor_settings()
            if configured_theme != old_theme:
                _write_setting("cursorTheme", old_theme)
            if configured_size != old_size:
                _write_setting("cursorSize", str(old_size))
        except (OSError, subprocess.SubprocessError, SkinError):
            # Report the original apply failure even when rollback fails.
            pass
        raise SkinError(error_message) from error


def notice() -> str | None:
    return _("Log out and back in to finish applying the Plasma cursor theme.") if _relogin else None


def screen_size() -> tuple[int, int]:
    try:
        outputs = json.loads(_run("kscreen-doctor", "--json").stdout)["outputs"]
        enabled = [output for output in outputs if output["connected"] and output["enabled"]]
        primary = min(enabled, key=lambda output: output.get("priority") or
                      (1 if output.get("primary") else math.inf))
        mode = next(mode for mode in primary["modes"] if mode["id"] == primary["currentModeId"])
        scale = float(primary["scale"])
        width, height = (round(mode["size"][key] / scale) for key in ("width", "height"))
        if primary["rotation"] in (2, 8, 32, 128):
            width, height = height, width
        if scale > 0 and width > 0 and height > 0:
            return width, height
    except (OSError, subprocess.SubprocessError, KeyError, StopIteration,
            ValueError, TypeError, ZeroDivisionError, OverflowError):
        pass
    # shortcut: use the existing default when KScreen is unavailable, surface a
    # display selection if users need a different fallback.
    return 1920, 1080


def effect_status() -> str:
    if _effect_call("isEffectLoaded", "(s)", (EFFECT_ID,)):
        return "active"
    return "disabled" if _effect_call("isEffectSupported", "(s)", (EFFECT_ID,)) else "unavailable"


def _effect_call(method: str, signature: str, args: tuple[str, ...]) -> bool | str | None:
    if os.environ.get("XDG_SESSION_TYPE") != "wayland":
        return None
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    try:
        return Gio.bus_get_sync(Gio.BusType.SESSION).call_sync(
            "org.kde.KWin", "/Effects", "org.kde.kwin.Effects", method,
            GLib.Variant(signature, args), None, Gio.DBusCallFlags.NONE, 1000, None,
        ).unpack()[0]
    except GLib.Error:
        return None


def trail_problem(state: dict, directory: Path) -> str | None:
    try:
        trail = state["trail"]
        filename = trail["file"]
        if (state["version"] != 1 or not THEME_PATTERN.fullmatch(state["theme"])
                or not re.fullmatch(r"trail-[0-9a-f]{12}\.rgba", filename)
                or (directory / filename).stat().st_size != trail["width"] * trail["height"] * 4):
            return _("The Plasma trail data could not be loaded.")
    except (OSError, KeyError, TypeError):
        return _("The Plasma trail data could not be loaded.")
    status = effect_status()
    if status == "disabled":
        return _("Enable Cursor for osu! Trail in Plasma Desktop Effects.")
    if status == "unavailable":
        return _("The trail effect is not loaded yet. Log out and back in once.")
    if _effect_call("debug", "(ss)", (EFFECT_ID, "state")) == "invalid":
        return _("The Plasma trail data could not be loaded.")
    return None
