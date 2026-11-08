"""Install a generated skin on GNOME and restore the previous cursor."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import render, xcursor
from .skin import Skin, SkinError, read_cursor_files, skin_from_files

EXTENSION_UUID = "osu-cursor-trail@xrayzack1010.github.io"
THEME_PATTERN = re.compile(r"^osu-cursor-[0-9a-f]{12}$")
THEME_MARKER = ".osu-cursor"
TRAIL_INTERVAL_DIVISOR = 2.5
EXTENSION_STATE_ACTIVE = 1
MIN_CURSOR_SIZE = 0.1  # same limits as the game's cursor size slider
MAX_CURSOR_SIZE = 2.0

# Every shape applications may ask for points at the one skin cursor.
CURSOR_NAMES = """
default arrow left_ptr top_left_arrow right_ptr context-menu help question_arrow
pointer hand hand1 hand2 pointing_hand progress left_ptr_watch wait watch
cell crosshair cross tcross plus text xterm ibeam vertical-text
alias dnd-link copy dnd-copy move dnd-move fleur grab openhand dnd-none grabbing
closedhand no-drop dnd-no-drop not-allowed forbidden circle crossed_circle
all-scroll size_all e-resize right_side n-resize top_side ne-resize top_right_corner
nw-resize top_left_corner s-resize bottom_side se-resize bottom_right_corner
sw-resize bottom_left_corner w-resize left_side ew-resize h_double_arrow sb_h_double_arrow
size_hor col-resize split_h ns-resize v_double_arrow sb_v_double_arrow size_ver
row-resize split_v nesw-resize fd_double_arrow size_bdiag nwse-resize bd_double_arrow
size_fdiag zoom-in zoom-out pirate center_ptr
""".split()


@dataclass
class Result:
    skin_name: str
    has_trail: bool
    trail_active: bool
    size_px: int


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    return Path(base) / "osu-cursor"


def icons_dir() -> Path:
    return data_dir().parent / "icons"


def _gsettings(*args: str) -> str:
    done = subprocess.run(
        ["gsettings", *args], check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


def _interface_get(key: str) -> str:
    return _gsettings("get", "org.gnome.desktop.interface", key)


def _interface_set(key: str, value: str) -> None:
    _gsettings("set", "org.gnome.desktop.interface", key, value)


def screen_size() -> tuple[int, int]:
    """Logical size of the primary monitor, or 1920x1080 if Mutter can't be asked."""
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    try:
        reply = Gio.bus_get_sync(Gio.BusType.SESSION).call_sync(
            "org.gnome.Mutter.DisplayConfig",
            "/org/gnome/Mutter/DisplayConfig",
            "org.gnome.Mutter.DisplayConfig",
            "GetCurrentState",
            None,
            None,
            Gio.DBusCallFlags.NONE,
            2000,
            None,
        ).unpack()
    except GLib.Error:
        return 1920, 1080

    _serial, monitors, logical_monitors, _properties = reply
    modes = {}
    for spec, monitor_modes, _monitor_properties in monitors:
        for mode in monitor_modes:
            if mode[6].get("is-current"):
                modes[spec[0]] = mode

    for _x, _y, scale, transform, primary, specs, _props in logical_monitors:
        if primary and specs and specs[0][0] in modes:
            mode = modes[specs[0][0]]
            width, height = mode[1] / scale, mode[2] / scale
            if transform % 2:  # 90 and 270 degree rotations swap the sides
                width, height = height, width
            return round(width), round(height)
    return 1920, 1080


def game_cursor_size() -> float:
    """The user's in-game cursor size, taken from osu!lazer's settings if present."""
    config = data_dir().parent / "osu" / "game.ini"
    try:
        match = re.search(
            r"^GameplayCursorSize\s*=\s*([0-9.]+)", config.read_text(), re.MULTILINE
        )
    except OSError:
        return 1.0
    return float(match.group(1)) if match else 1.0


def _skin_id(skin: Skin, scale: float) -> str:
    digest = hashlib.sha256(f"{scale:.4f}".encode())
    digest.update(f"{skin.cursor_centre}{skin.cursor_rotate}".encode())
    for sprite in (skin.cursor, skin.middle):
        if sprite:
            digest.update(sprite.image.tobytes())
    return digest.hexdigest()[:12]


def _write_theme(skin: Skin, scale: float, nominal_size: int) -> str:
    name = f"osu-cursor-{_skin_id(skin, scale)}"
    theme = icons_dir() / name
    temporary = icons_dir() / f".{name}.tmp"
    shutil.rmtree(temporary, ignore_errors=True)
    cursors = temporary / "cursors"
    cursors.mkdir(parents=True)

    frames = render.build_frames(skin, scale)
    (cursors / "left_ptr").write_bytes(xcursor.encode(frames, nominal_size))
    for cursor_name in CURSOR_NAMES:
        if cursor_name != "left_ptr":
            (cursors / cursor_name).symlink_to("left_ptr")

    (temporary / "index.theme").write_text(
        f"[Icon Theme]\nName={skin.name}\nComment=Generated by osu-cursor\n"
    )
    (temporary / THEME_MARKER).touch()

    shutil.rmtree(theme, ignore_errors=True)
    temporary.rename(theme)
    return name


def _remove_old_themes(keep: str | None) -> None:
    directory = icons_dir()
    if not directory.is_dir():
        return
    for entry in directory.iterdir():
        if (
            entry.name != keep
            and THEME_PATTERN.match(entry.name)
            and (entry / THEME_MARKER).exists()
        ):
            shutil.rmtree(entry)


def _atomic_write(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def _write_trail_state(skin: Skin, scale: float, cursor_size: float) -> None:
    directory = data_dir()
    directory.mkdir(parents=True, exist_ok=True)

    state: dict = {"version": 1, "skin": skin.name, "trail": None}
    keep = set()
    if skin.trail:
        pixels = skin.trail.image.convert("RGBa").tobytes()
        file_name = f"trail-{hashlib.sha256(pixels).hexdigest()[:12]}.rgba"
        _atomic_write(directory / file_name, pixels)
        keep.add(file_name)

        display_width, display_height = skin.trail.display_size
        # IntervalMultiplier in LegacyCursorTrail cancels cursor sizes above 1.
        interval = display_width * scale / TRAIL_INTERVAL_DIVISOR / max(cursor_size, 1)
        state["trail"] = {
            "file": file_name,
            "width": skin.trail.image.width,
            "height": skin.trail.image.height,
            "display_width": display_width * scale,
            "display_height": display_height * scale,
            "interval": interval,
            "disjoint": skin.disjoint_trail,
            "rotate": skin.cursor_trail_rotate and skin.cursor_rotate,
            "centre": skin.cursor_centre or not skin.disjoint_trail,
        }

    _atomic_write(
        directory / "state.json", json.dumps(state, ensure_ascii=False).encode()
    )
    for entry in directory.glob("trail-*.rgba"):
        if entry.name not in keep:
            entry.unlink()


def _clear_trail_state() -> None:
    directory = data_dir()
    if directory.is_dir():
        _atomic_write(
            directory / "state.json",
            json.dumps({"version": 1, "skin": None, "trail": None}).encode(),
        )
        for entry in directory.glob("trail-*.rgba"):
            entry.unlink()


def enable_extension() -> None:
    """Turn the extension on, including for the next login if it isn't loaded yet."""
    enabled = ast.literal_eval(
        _gsettings("get", "org.gnome.shell", "enabled-extensions").removeprefix("@as ")
    )
    if EXTENSION_UUID not in enabled:
        enabled.append(EXTENSION_UUID)
        _gsettings("set", "org.gnome.shell", "enabled-extensions", str(enabled))


def extension_active() -> bool:
    """Ask GNOME Shell whether the trail extension is running right now."""
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    try:
        reply = Gio.bus_get_sync(Gio.BusType.SESSION).call_sync(
            "org.gnome.Shell",
            "/org/gnome/Shell",
            "org.gnome.Shell.Extensions",
            "GetExtensionInfo",
            GLib.Variant("(s)", (EXTENSION_UUID,)),
            None,
            Gio.DBusCallFlags.NONE,
            2000,
            None,
        ).unpack()[0]
    except GLib.Error:
        return False
    return reply.get("state") == EXTENSION_STATE_ACTIVE


def _settings_path() -> Path:
    return data_dir() / "settings.json"


def cursor_size() -> float:
    """The size chosen in this app, or else the one set in osu!lazer."""
    try:
        return float(json.loads(_settings_path().read_text())["cursor_size"])
    except (OSError, ValueError, KeyError, TypeError):
        return min(MAX_CURSOR_SIZE, max(MIN_CURSOR_SIZE, game_cursor_size()))


def _save_cursor_size(size: float) -> None:
    if not MIN_CURSOR_SIZE <= size <= MAX_CURSOR_SIZE:
        raise SkinError(f"Boyut {MIN_CURSOR_SIZE} ile {MAX_CURSOR_SIZE} arasında olmalı.")
    data_dir().mkdir(parents=True, exist_ok=True)
    _atomic_write(_settings_path(), json.dumps({"cursor_size": size}).encode())


def _source_dir() -> Path:
    return data_dir() / "source"


def _current_source() -> Path | None:
    return next(_source_dir().glob("*.osk"), None)


def _keep_source(files: dict[str, bytes], stem: str) -> None:
    """Keep the cursor files so the size can change without dropping the skin again."""
    shutil.rmtree(_source_dir(), ignore_errors=True)
    _source_dir().mkdir(parents=True)
    with zipfile.ZipFile(_source_dir() / f"{stem}.osk", "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)


def apply_skin(path: str | os.PathLike, size: float | None = None) -> Result:
    files = read_cursor_files(path)
    stem = Path(path).stem
    skin = skin_from_files(files, stem)

    if size is not None:
        _save_cursor_size(size)
    else:
        size = cursor_size()

    width, height = screen_size()
    scale = render.gameplay_scale(width, height, size)
    system_size = int(_interface_get("cursor-size"))

    theme = _write_theme(skin, scale, system_size)
    _write_trail_state(skin, scale, size)
    _keep_source(files, stem)

    current = _interface_get("cursor-theme").strip("'")
    previous = data_dir() / "previous.json"
    if not THEME_PATTERN.match(current):
        _atomic_write(
            previous, json.dumps({"theme": current, "size": system_size}).encode()
        )

    _interface_set("cursor-theme", theme)
    _remove_old_themes(keep=theme)
    enable_extension()

    display_width = skin.cursor.display_size[0] * scale
    return Result(skin.name, skin.trail is not None, extension_active(), round(display_width))


def set_cursor_size(size: float) -> Result | None:
    """Change the size and redraw the current skin, if there is one."""
    _save_cursor_size(size)
    source = _current_source()
    return apply_skin(source, size) if source else None


def reset() -> str | None:
    """Go back to the cursor used before the first skin. Returns its theme name."""
    previous_path = data_dir() / "previous.json"
    restored = None
    try:
        previous = json.loads(previous_path.read_text())
    except (OSError, ValueError):
        previous = None

    if previous:
        _interface_set("cursor-theme", previous["theme"])
        _interface_set("cursor-size", str(previous["size"]))
        restored = previous["theme"]
    elif THEME_PATTERN.match(_interface_get("cursor-theme").strip("'")):
        _gsettings("reset", "org.gnome.desktop.interface", "cursor-theme")
        restored = _interface_get("cursor-theme").strip("'")

    _clear_trail_state()
    _remove_old_themes(keep=None)
    shutil.rmtree(_source_dir(), ignore_errors=True)
    previous_path.unlink(missing_ok=True)
    return restored


def current_skin() -> str | None:
    try:
        return json.loads((data_dir() / "state.json").read_text()).get("skin")
    except (OSError, ValueError):
        return None


def trail_problem() -> str | None:
    """Explain why the current skin shows no trail, or None if it should show one."""
    try:
        state = json.loads((data_dir() / "state.json").read_text())
    except (OSError, ValueError):
        return None
    if not state.get("skin"):
        return None
    if not state.get("trail"):
        return "Bu skin'in trail'i yok, oyunda da görünmez."
    if not extension_active():
        return "Trail'in görünmesi için bir kez oturumu kapatıp tekrar aç."
    return None
