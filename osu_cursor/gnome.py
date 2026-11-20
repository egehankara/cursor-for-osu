"""Manage skins and apply generated cursor themes on GNOME and Plasma."""

from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import threading
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from . import plasma, render, system, xcursor
from .i18n import _
from .skin import Skin, SkinError, read_cursor_files, skin_from_files, skin_stem

EXTENSION_UUID = "cursor-for-osu-trail@egehankara.github.io"
OLD_EXTENSION_UUIDS = ("osu-cursor-trail@xrayzack1010.github.io",)  # earlier names, turned off when installing
THEME_PATTERN = re.compile(r"^osu-cursor-[0-9a-f]{12}$")
THEME_MARKER = ".osu-cursor"
NAME_ENTRY = "display-name.txt"  # the name given in the app, kept inside the archive
MAX_NAME_BYTES = 1024
EXTENSION_STATE_ACTIVE = 1
EXTENSION_STATE_INACTIVE = 2
EXTENSION_STATE_ERROR = 3
EXTENSION_STATE_OUT_OF_DATE = 4
EXTENSION_STATE_INITIALIZED = 6
PREVIEW_WIDTH = 96
PREVIEW_HEIGHT = 48
MIN_CURSOR_SIZE = 0.1  # same limits as the game's cursor size slider
MAX_CURSOR_SIZE = 2.0
MIN_SCREEN_SCALING = 0.2  # lower limit of the game's screen scaling sliders

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


@dataclass
class LibrarySkin:
    path: Path
    name: str
    key: str  # same for skins whose cursor files are identical
    has_trail: bool
    preview_png: bytes


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    return Path(base) / "osu-cursor"


def skins_dir() -> Path:
    """Where the skins added in the app are kept, one cursor-only folder each."""
    return data_dir() / "skins"


# Files only an osu!lazer data folder has, at least one of them.
OSU_DIR_MARKERS = ("client.realm", "game.ini", "framework.ini", "storage.ini")


def _moved_to(base: Path) -> Path | None:
    """The folder storage.ini in base points to, if it names one that exists."""
    try:
        match = re.search(
            r"^FullPath\s*=\s*(.+?)\s*$", (base / "storage.ini").read_text(), re.MULTILINE
        )
    except (OSError, UnicodeDecodeError):
        return None
    return Path(match.group(1)) if match and Path(match.group(1)).is_dir() else None


def osu_dir() -> Path:
    """Where osu!lazer keeps its settings and exports.

    A folder chosen in the app comes first. Otherwise it is looked for: the game can be
    told to keep its files in another folder, it then writes that folder into storage.ini.
    The Flatpak build keeps them inside its own sandbox folder.
    """
    chosen = chosen_osu_dir()
    if chosen is not None and chosen.is_dir():
        return _moved_to(chosen) or chosen
    default = data_dir().parent / "osu"
    flatpak = Path.home() / ".var/app/sh.ppy.osu/data/osu"
    for base in (default, flatpak):
        moved = _moved_to(base)
        if moved:
            return moved
    if not default.is_dir() and flatpak.is_dir():
        return flatpak
    return default


def chosen_osu_dir() -> Path | None:
    """The osu!lazer folder picked by hand in the app, None when it is found on its own."""
    chosen = _settings().get("osu_dir")
    return Path(chosen) if isinstance(chosen, str) and chosen else None


def set_osu_dir(path: str | os.PathLike | None) -> None:
    """Use this folder as osu!lazer's, or look for it on its own again with None."""
    if path is not None:
        path = Path(path)
        if not any((path / name).exists() for name in OSU_DIR_MARKERS):
            raise SkinError(_(
                "This doesn't look like an osu!lazer folder. "
                "Choose the one that has game.ini and client.realm in it."
            ))
    with _write_lock:
        settings = _settings()
        if path is None:
            settings.pop("osu_dir", None)
        else:
            settings["osu_dir"] = str(path)
        data_dir().mkdir(parents=True, exist_ok=True)
        _atomic_write(_settings_path(), json.dumps(settings).encode())


def exports_dir() -> Path:
    return osu_dir() / "exports"


def icons_dir() -> Path:
    return data_dir().parent / "icons"


def _desktop_dir() -> Path:
    return data_dir() / "plasma" if plasma.selected() else data_dir()


def desktop_notice() -> str | None:
    return plasma.notice() if plasma.selected() else None


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
    if plasma.selected():
        return plasma.screen_size()
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


def _game_setting(name: str) -> str | None:
    """A value from osu!lazer's game.ini, if the game is installed."""
    config = osu_dir() / "game.ini"
    try:
        match = re.search(rf"^{name}\s*=\s*(.+?)\s*$", config.read_text(), re.MULTILINE)
    except OSError:
        return None
    return match.group(1) if match else None


def _game_float(name: str, default: float) -> float:
    try:
        return float(_game_setting(name) or default)
    except ValueError:
        return default


def game_cursor_size() -> float:
    """The user's in-game cursor size, taken from osu!lazer's settings if present."""
    return clamp_cursor_size(_game_float("GameplayCursorSize", 1.0))


def has_game_cursor_size() -> bool:
    return _game_setting("GameplayCursorSize") is not None


def clamp_cursor_size(size: float) -> float:
    return min(MAX_CURSOR_SIZE, max(MIN_CURSOR_SIZE, size))


def gameplay_area(screen_width: int, screen_height: int) -> tuple[float, float]:
    """The screen area osu! plays in. Its Screen Scaling setting shrinks the cursor too."""
    if (_game_setting("Scaling") or "Off").lower() == "off":
        return screen_width, screen_height
    return (
        screen_width * min(1.0, max(MIN_SCREEN_SCALING, _game_float("ScalingSizeX", 1.0))),
        screen_height * min(1.0, max(MIN_SCREEN_SCALING, _game_float("ScalingSizeY", 1.0))),
    )


def _skin_id(skin: Skin, scale: float, system_theme: str | None) -> str:
    digest = hashlib.sha256(f"{scale:.4f}".encode())
    if system_theme is not None:
        digest.update(f"system {system_theme}".encode())
    digest.update(f"still {skin.cursor_centre}".encode())
    for sprite in (skin.cursor, skin.middle):
        if sprite:
            digest.update(sprite.image.tobytes())
    return digest.hexdigest()[:12]


def _write_theme(
    skin: Skin, scale: float, nominal_size: int, system_theme: str | None
) -> tuple[str, xcursor.Frame]:
    """Write a cursor theme for the skin. With system_theme, shapes like text and resize come from it.

    Returns the theme name and the skin cursor's frame.
    """
    frames = render.build_frames(skin, scale)  # first, it refuses cursors that are too large
    kde = plasma.selected()
    prefix = plasma.THEME_PREFIX if kde else "osu-cursor-"
    digest = _skin_id(skin, scale, system_theme)
    if kde:
        frame = frames[0]
        digest = hashlib.sha256(
            f"{digest}:{nominal_size}:{frame.image.size}:{frame.hot_x}:{frame.hot_y}:{skin.name}".encode()
        ).hexdigest()[:12]
    name = prefix + digest
    theme = icons_dir() / name
    if kde and (theme / THEME_MARKER).is_file():
        return name, frames[0]
    temporary = icons_dir() / f".{name}.tmp"
    shutil.rmtree(temporary, ignore_errors=True)
    cursors = temporary / "cursors"
    cursors.mkdir(parents=True)

    (cursors / "left_ptr").write_bytes(xcursor.encode(frames, nominal_size))
    for cursor_name in CURSOR_NAMES:
        if cursor_name != "left_ptr":
            (cursors / cursor_name).symlink_to("left_ptr")
    if system_theme is not None:
        system.write_shapes(cursors, system_theme, system.skin_colour(skin.cursor.image))

    (temporary / "index.theme").write_text(
        f"[Icon Theme]\nName={' '.join(skin.name.split())}\nComment=Generated by osu-cursor\n"
    )
    (temporary / THEME_MARKER).touch()

    shutil.rmtree(theme, ignore_errors=True)
    temporary.rename(theme)
    return name, frames[0]


def _remove_old_themes(keep: str | None) -> None:
    directory = icons_dir()
    if not directory.is_dir():
        return
    pattern = plasma.THEME_PATTERN if plasma.selected() else THEME_PATTERN
    for entry in directory.iterdir():
        if (
            entry.name != keep
            and pattern.fullmatch(entry.name)
            and not entry.is_symlink()
            and (entry / THEME_MARKER).exists()
        ):
            shutil.rmtree(entry)


# The window and its background jobs both write settings.json and state.json.
_write_lock = threading.RLock()


@contextmanager
def _desktop_lock() -> Iterator[None]:
    if not plasma.selected():
        yield
        return
    import fcntl

    directory = _desktop_dir()
    directory.mkdir(parents=True, exist_ok=True)
    with _write_lock, (directory / "cursor.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _atomic_write(path: Path, data: bytes) -> None:
    # Each writer gets its own temporary file, so two writes can't mix.
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def _write_trail_state(
    skin: Skin, scale: float, cursor_size: float, own_cursor: xcursor.Frame | None,
    *, theme: str | None = None,
) -> None:
    """Tell the extension how to draw the trail.

    With own_cursor, the trail is only drawn while that cursor is shown, so the
    kept system cursors don't get one.
    """
    directory = _desktop_dir()
    directory.mkdir(parents=True, exist_ok=True)

    state: dict = {
        "version": 1,
        "skin": skin.name,
        "trail": None,
        "trail_enabled": trail_enabled(),
        "skin_cursor": None,
    }
    if theme is not None:
        state["theme"] = theme
    if own_cursor is not None:
        state["skin_cursor"] = {
            "width": own_cursor.image.width,
            "height": own_cursor.image.height,
            "hot_x": own_cursor.hot_x,
            "hot_y": own_cursor.hot_y,
        }
    keep = set()
    if skin.trail:
        pixels = skin.trail.image.convert("RGBa").tobytes()
        file_name = f"trail-{hashlib.sha256(pixels).hexdigest()[:12]}.rgba"
        _atomic_write(directory / file_name, pixels)
        keep.add(file_name)

        display_width, display_height = skin.trail.display_size
        # IntervalMultiplier in LegacyCursorTrail cancels cursor sizes above 1.
        interval = display_width * scale / render.TRAIL_INTERVAL_DIVISOR / max(cursor_size, 1)
        state["trail"] = {
            "file": file_name,
            "width": skin.trail.image.width,
            "height": skin.trail.image.height,
            "display_width": display_width * scale,
            "display_height": display_height * scale,
            "interval": interval,
            "disjoint": skin.disjoint_trail,
            "centre": skin.cursor_centre or not skin.disjoint_trail,
        }

    with _write_lock:
        _atomic_write(directory / "state.json", json.dumps(state, ensure_ascii=False).encode())
    for entry in directory.glob("trail-*.rgba"):
        if entry.name not in keep:
            entry.unlink()


def _clear_trail_state() -> None:
    directory = _desktop_dir()
    if directory.is_dir():
        with _write_lock:
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
    wanted = [uuid for uuid in enabled if uuid not in OLD_EXTENSION_UUIDS]
    if EXTENSION_UUID not in wanted:
        wanted.append(EXTENSION_UUID)
    if wanted != enabled:
        _gsettings("set", "org.gnome.shell", "enabled-extensions", str(wanted))


def _extension_info() -> dict:
    """What GNOME Shell knows about the trail extension, empty if it hasn't seen it."""
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    try:
        return Gio.bus_get_sync(Gio.BusType.SESSION).call_sync(
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
        return {}


def extension_active() -> bool:
    """Ask GNOME Shell whether the trail extension is running right now."""
    if plasma.selected():
        return plasma.effect_status() == "active"
    return _extension_info().get("state") == EXTENSION_STATE_ACTIVE


def _settings_path() -> Path:
    return data_dir() / "settings.json"


def _settings() -> dict:
    try:
        settings = json.loads(_settings_path().read_text())
    except (OSError, ValueError):
        return {}
    return settings if isinstance(settings, dict) else {}


def _save_setting(key: str, value: object) -> None:
    with _write_lock:
        data_dir().mkdir(parents=True, exist_ok=True)
        settings = _settings()
        settings[key] = value
        _atomic_write(_settings_path(), json.dumps(settings).encode())


def cursor_size() -> float:
    """The size chosen in this app, or else the one set in osu!lazer."""
    try:
        return float(_settings()["cursor_size"])
    except (ValueError, KeyError, TypeError):
        return game_cursor_size()


def _save_cursor_size(size: float) -> None:
    _validate_cursor_size(size)
    _save_setting("cursor_size", size)


def _validate_cursor_size(size: float) -> None:
    if not MIN_CURSOR_SIZE <= size <= MAX_CURSOR_SIZE:
        raise SkinError(_("The size has to be between {low} and {high}.").format(low=MIN_CURSOR_SIZE, high=MAX_CURSOR_SIZE))


def watch_exports_enabled() -> bool:
    return _settings().get("watch_exports") is not False


def set_watch_exports_enabled(enabled: bool) -> None:
    _save_setting("watch_exports", enabled)


def update_check_enabled() -> bool:
    return _settings().get("check_updates") is not False


def set_update_check_enabled(enabled: bool) -> None:
    _save_setting("check_updates", enabled)


def skipped_update() -> str | None:
    """The version the user said "not now" to, it isn't offered again."""
    skipped = _settings().get("skipped_update")
    return skipped if isinstance(skipped, str) else None


def skip_update(version: str) -> None:
    _save_setting("skipped_update", version)


def cached_release() -> dict | None:
    """The latest release seen on GitHub and when it was asked, see update.py."""
    cached = _settings().get("latest_release")
    if (isinstance(cached, dict) and isinstance(cached.get("version"), str)
            and isinstance(cached.get("url"), str)
            and isinstance(cached.get("checked_at"), (int, float))):
        return cached
    return None


def cache_release(version: str, url: str, checked_at: float) -> None:
    _save_setting("latest_release", {"version": version, "url": url, "checked_at": checked_at})


def keep_system_cursors() -> bool:
    return _settings().get("keep_system_cursors") is True


def set_keep_system_cursors(enabled: bool) -> Result | None:
    """Turn the system text, resize and similar cursors on or off and redraw the current skin."""
    _save_setting("keep_system_cursors", enabled)
    source = _current_source()
    return apply_skin(source) if source else None


def _system_theme() -> str:
    """The cursor theme in use before the first skin, where the system shapes come from."""
    current = _interface_get("cursor-theme").strip("'")
    if not THEME_PATTERN.match(current):
        return current
    try:
        return str(json.loads((data_dir() / "previous.json").read_text())["theme"])
    except (OSError, ValueError, KeyError, TypeError):
        return system.FALLBACK_THEME


def trail_enabled() -> bool:
    return _settings().get("trail_enabled") is not False


def set_trail_enabled(enabled: bool) -> None:
    """Turn the trail on or off without rebuilding the cursor."""
    path = _desktop_dir() / "state.json"
    with _desktop_lock(), _write_lock:
        _save_setting("trail_enabled", enabled)
        try:
            state = json.loads(path.read_text())
        except (OSError, ValueError):
            return
        if isinstance(state, dict):
            state["trail_enabled"] = enabled
            _atomic_write(path, json.dumps(state, ensure_ascii=False).encode())


def _files_key(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode())
        digest.update(files[name])
    return digest.hexdigest()


def _write_archive(path: Path, files: dict[str, bytes]) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    _atomic_write(path, buffer.getvalue())


def _migrate_archives() -> None:
    """Turn the .osk files of older versions into folders."""
    for path in sorted(skins_dir().glob("*.osk")):
        if not path.is_file():
            continue
        try:
            files = read_cursor_files(path)
        except (SkinError, zipfile.BadZipFile, OSError):
            continue
        custom_name = _custom_name(path)
        if custom_name:
            files[NAME_ENTRY] = custom_name.encode()
        _store_skin(files, path.stem)
        path.unlink()


def _stored_skins() -> Iterator[tuple[Path, dict[str, bytes]]]:
    """The readable skin folders in the library, with their cursor files."""
    directory = skins_dir()
    if not directory.is_dir():
        return
    _migrate_archives()
    for path in sorted(directory.iterdir()):
        if not path.is_dir() or path.name.startswith("."):
            continue
        try:
            yield path, read_cursor_files(path)
        except (SkinError, OSError):  # OSError: it was removed while the list was being read
            continue


def library_skins() -> list[LibrarySkin]:
    """The skins added in the app, sorted by name."""
    skins = []
    for path, files in _stored_skins():
        try:
            skin = skin_from_files(files, path.name)
        except SkinError:
            continue
        image = io.BytesIO()
        render.preview(skin, PREVIEW_WIDTH, PREVIEW_HEIGHT).save(image, "PNG")
        skins.append(
            LibrarySkin(
                path,
                _custom_name(path) or " ".join(skin.name.split()),
                _files_key(files),
                skin.trail is not None,
                image.getvalue(),
            )
        )
    return sorted(skins, key=lambda skin: skin.name.casefold())


def add_skin(path: str | os.PathLike) -> None:
    """Copy the cursor files of a skin into the library. The original is left alone."""
    files = read_cursor_files(path)
    stem = skin_stem(path)
    skin_from_files(files, stem)  # refuses skins with no usable cursor

    key = _files_key(files)
    if any(_files_key(stored) == key for _path, stored in _stored_skins()):
        raise SkinError(_("This skin is already in the list."))

    _store_skin(files, stem)


def add_skins(paths: list[str]) -> tuple[int, int]:
    """Add several skins, going on after a bad one. Returns (added, skipped)."""
    added = skipped = 0
    for path in paths:
        try:
            add_skin(path)
            added += 1
        except (SkinError, zipfile.BadZipFile, OSError):
            skipped += 1
    return added, skipped


def add_new_exports(everything: bool = False) -> int:
    """Add the skins exported from osu!lazer since the last look. Returns how many were new.

    Each export file is looked at once, so a skin removed from the list stays removed.
    With everything, all exports are looked at again, removed skins come back too.
    Files that can't be read yet, such as one the game is still writing, are tried again later.
    """
    directory = exports_dir()
    if not directory.is_dir():
        return 0

    saved = _settings().get("seen_exports")
    saved = sorted(name for name in saved if isinstance(name, str)) if isinstance(saved, list) else []
    seen = set(saved)
    present = set()
    known = {_files_key(stored) for _path, stored in _stored_skins()}
    added = 0
    # Shortest name first, so "skin.osk" wins over its repeat "skin (1).osk".
    for path in sorted(directory.iterdir(), key=lambda path: (len(path.name), path.name)):
        if path.suffix.lower() != ".osk" or not path.is_file():
            continue
        present.add(path.name)
        if path.name in seen and not everything:
            continue
        try:
            if not zipfile.is_zipfile(path):
                continue  # unfinished or broken, looked at again next time
        except OSError:
            continue
        try:
            files = read_cursor_files(path)
            skin_from_files(files, path.stem)
        except SkinError:
            seen.add(path.name)  # readable but has no usable cursor
            continue
        except (zipfile.BadZipFile, OSError):
            continue  # one bad export should not stop the others
        seen.add(path.name)
        key = _files_key(files)
        if key not in known:
            _store_skin(files, path.stem)
            known.add(key)
            added += 1
    # Forget deleted exports, so the list doesn't grow forever.
    if sorted(seen & present) != saved:
        _save_setting("seen_exports", sorted(seen & present))
    return added


def _store_skin(files: dict[str, bytes], stem: str) -> None:
    directory = skins_dir()
    directory.mkdir(parents=True, exist_ok=True)
    stem = stem.lstrip(".") or "skin"  # names starting with a dot are skipped as temporary
    target = directory / stem
    number = 2
    while target.exists():
        target = directory / f"{stem} ({number})"
        number += 1

    temporary = directory / f".{target.name}.tmp"
    shutil.rmtree(temporary, ignore_errors=True)
    temporary.mkdir()
    for name, data in files.items():
        (temporary / name).write_bytes(data)
    temporary.rename(target)


def remove_skin(path: str | os.PathLike) -> None:
    """Delete a skin from the library. If it is in use, go back to the previous cursor."""
    path = Path(path)
    if path.parent != skins_dir():
        raise SkinError(_("This file is not part of the skin list."))
    if path.exists():
        in_use = _files_key(read_cursor_files(path)) == current_skin_key()
        if in_use:
            reset()
        shutil.rmtree(path)


def _custom_name(path: Path | str | os.PathLike) -> str | None:
    """The name given to a skin in the app, if it has one."""
    path = Path(path)
    try:
        if path.is_dir():
            entry = path / NAME_ENTRY
            if entry.stat().st_size > MAX_NAME_BYTES:
                return None
            data = entry.read_bytes()
        else:
            with zipfile.ZipFile(path) as archive:
                info = archive.getinfo(NAME_ENTRY)
                if info.file_size > MAX_NAME_BYTES:
                    return None
                data = archive.read(info)
        return data.decode().strip() or None
    except (KeyError, OSError, UnicodeDecodeError, zipfile.BadZipFile):
        return None


def rename_skin(path: str | os.PathLike, name: str) -> None:
    """Give a library skin a new name. The skin's own files stay as they are."""
    path = Path(path)
    if path.parent != skins_dir():
        raise SkinError(_("This file is not part of the skin list."))
    name = " ".join(name.split())
    if not name:
        raise SkinError(_("The name can't be empty."))
    if len(name.encode()) > MAX_NAME_BYTES:
        raise SkinError(_("This name is too long."))

    files = read_cursor_files(path)
    _atomic_write(path / NAME_ENTRY, name.encode())

    source = _current_source()
    if source is not None:
        applied = read_cursor_files(source)
        if _files_key(applied) == _files_key(files):
            _write_archive(source, {**applied, NAME_ENTRY: name.encode()})


def current_skin_key() -> str | None:
    """Identifies the applied skin, comparable with LibrarySkin.key."""
    source = _current_source()
    if source is None:
        return None
    try:
        return _files_key(read_cursor_files(source))
    except SkinError:
        return None


def _source_dir() -> Path:
    return _desktop_dir() / "source"


def _current_source() -> Path | None:
    return next(_source_dir().glob("*.osk"), None)


def _keep_source(files: dict[str, bytes], stem: str) -> None:
    """Keep the cursor files so the size can change without dropping the skin again."""
    directory = _source_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{stem}.osk"
    _write_archive(target, files)
    for previous in directory.glob("*.osk"):
        if previous != target:
            previous.unlink()


def apply_skin(path: str | os.PathLike, size: float | None = None) -> Result:
    with _desktop_lock():
        return _apply_skin(path, size)


def _apply_skin(path: str | os.PathLike, size: float | None) -> Result:
    files = read_cursor_files(path)
    stem = skin_stem(path)
    skin = skin_from_files(files, stem)
    custom_name = _custom_name(path)
    if custom_name:
        skin.name = custom_name

    explicit_size = size
    size = cursor_size() if size is None else size
    _validate_cursor_size(size)

    width, height = gameplay_area(*screen_size())
    scale = render.gameplay_scale(width, height, size)
    keep_system = keep_system_cursors()
    source = {**files, NAME_ENTRY: custom_name.encode()} if custom_name else files
    if plasma.selected():
        _apply_plasma_skin(skin, scale, size, keep_system, source, stem)
        if explicit_size is not None:
            _save_cursor_size(size)
        return Result(skin.name, skin.trail is not None, extension_active(),
                      round(skin.cursor.display_size[0] * scale))

    if explicit_size is not None:
        _save_cursor_size(size)
    system_size = int(_interface_get("cursor-size"))

    theme, cursor = _write_theme(skin, scale, system_size, _system_theme() if keep_system else None)
    _write_trail_state(skin, scale, size, cursor if keep_system else None)
    _keep_source(source, stem)

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


def _plasma_previous(path: Path) -> tuple[str, int]:
    try:
        data = json.loads(path.read_text())
        theme, size = data["theme"], data["size"]
        if (isinstance(theme, str) and theme and not plasma.THEME_PATTERN.fullmatch(theme)
                and type(size) is int and size >= 0):
            return theme, size
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return plasma.DEFAULT_THEME, plasma.DEFAULT_SIZE


def _apply_plasma_skin(
    skin: Skin, scale: float, size: float, keep_system: bool, source: dict[str, bytes], stem: str
) -> None:
    plasma.require_wayland()
    current, system_size = plasma.cursor_settings()
    previous = _desktop_dir() / "previous.json"
    owned = plasma.THEME_PATTERN.fullmatch(current)
    base_theme = _plasma_previous(previous)[0] if owned else current
    theme, cursor = _write_theme(skin, scale, system_size or plasma.DEFAULT_SIZE,
                                 base_theme if keep_system else None)
    backup = None
    if not owned:
        if previous.exists():
            backup = previous.read_bytes()
        _atomic_write(previous, json.dumps({"theme": current, "size": system_size}).encode())
    try:
        plasma.apply_theme(theme, system_size)
    except SkinError:
        if plasma.cursor_settings()[0] == theme and current != theme:
            plasma.apply_theme(current, system_size)
        if not owned:
            if backup is None:
                previous.unlink(missing_ok=True)
            else:
                _atomic_write(previous, backup)
        raise
    _keep_source(source, stem)
    _write_trail_state(skin, scale, size, cursor if keep_system else None, theme=theme)
    if not plasma.notice():
        _remove_old_themes(keep=theme)


def set_cursor_size(size: float) -> Result | None:
    """Change the size and redraw the current skin, if there is one."""
    source = _current_source()
    if source:
        return apply_skin(source, size)
    _save_cursor_size(size)
    return None


def reset() -> str | None:
    """Go back to the cursor used before the first skin. Returns its theme name."""
    with _desktop_lock():
        return _reset()


def _reset() -> str | None:
    if plasma.selected():
        plasma.require_wayland()
        previous_path = _desktop_dir() / "previous.json"
        restored = None
        if plasma.THEME_PATTERN.fullmatch(plasma.cursor_settings()[0]):
            theme, size = _plasma_previous(previous_path)
            plasma.apply_theme(theme, size)
            restored = theme
        _clear_trail_state()
        _remove_old_themes(keep=None)
        shutil.rmtree(_source_dir(), ignore_errors=True)
        previous_path.unlink(missing_ok=True)
        return restored

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
    (data_dir() / "extension-off.json").unlink(missing_ok=True)
    return restored


def current_skin() -> str | None:
    source = _current_source()
    custom_name = _custom_name(source) if source else None
    if custom_name:
        return custom_name
    try:
        return json.loads((_desktop_dir() / "state.json").read_text()).get("skin")
    except (OSError, ValueError, AttributeError):
        return None


def trail_problem() -> str | None:
    """Explain why the current skin shows no trail, or None if it should show one."""
    kde = plasma.selected()
    try:
        state = json.loads((_desktop_dir() / "state.json").read_text())
    except FileNotFoundError:
        if not kde or _current_source() is None:
            return None
        state = None
    except (OSError, ValueError):
        state = None
    if not trail_enabled():
        return None
    if not isinstance(state, dict) or (kde and state.get("version") != 1):
        return _("The Plasma trail data could not be loaded.") if kde else None
    if not state.get("skin") or not state.get("trail"):
        return None

    if kde:
        return plasma.trail_problem(state, _desktop_dir())

    info = _extension_info()
    status = info.get("state")
    if status == EXTENSION_STATE_ACTIVE:
        return None
    if status == EXTENSION_STATE_OUT_OF_DATE:
        return _("GNOME was updated and the trail extension doesn't support this version yet. Cursor for osu! needs an update.")
    if status == EXTENSION_STATE_ERROR:
        return _("The trail extension couldn't run: {error}").format(error=info.get("error") or _("unknown error"))
    if status in (EXTENSION_STATE_INACTIVE, EXTENSION_STATE_INITIALIZED):
        return _("The trail extension is turned off. Turn it on in the Extensions app.")
    return _("Log out and back in once to see the trail.")
