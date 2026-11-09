"""Install a generated skin on GNOME and restore the previous cursor."""

from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from . import render, xcursor
from .skin import Skin, SkinError, read_cursor_files, skin_from_files, skin_stem

EXTENSION_UUID = "osu-cursor-trail@xrayzack1010.github.io"
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


def exports_dir() -> Path:
    return data_dir().parent / "osu" / "exports"


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


def _game_setting(name: str) -> str | None:
    """A value from osu!lazer's game.ini, if the game is installed."""
    config = data_dir().parent / "osu" / "game.ini"
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


def _skin_id(skin: Skin, scale: float) -> str:
    digest = hashlib.sha256(f"{scale:.4f}".encode())
    digest.update(f"still {skin.cursor_centre}".encode())
    for sprite in (skin.cursor, skin.middle):
        if sprite:
            digest.update(sprite.image.tobytes())
    return digest.hexdigest()[:12]


def _write_theme(skin: Skin, scale: float, nominal_size: int) -> str:
    frames = render.build_frames(skin, scale)  # first, it refuses cursors that are too large
    name = f"osu-cursor-{_skin_id(skin, scale)}"
    theme = icons_dir() / name
    temporary = icons_dir() / f".{name}.tmp"
    shutil.rmtree(temporary, ignore_errors=True)
    cursors = temporary / "cursors"
    cursors.mkdir(parents=True)

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

    state: dict = {
        "version": 1,
        "skin": skin.name,
        "trail": None,
        "trail_enabled": trail_enabled(),
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
    if not MIN_CURSOR_SIZE <= size <= MAX_CURSOR_SIZE:
        raise SkinError(f"Boyut {MIN_CURSOR_SIZE} ile {MAX_CURSOR_SIZE} arasında olmalı.")
    _save_setting("cursor_size", size)


def trail_enabled() -> bool:
    return _settings().get("trail_enabled") is not False


def set_trail_enabled(enabled: bool) -> None:
    """Turn the trail on or off without rebuilding the cursor."""
    _save_setting("trail_enabled", enabled)
    path = data_dir() / "state.json"
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        return
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
        raise SkinError("Bu skin zaten listede.")

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


def add_exported_skins() -> int:
    """Add the usable skins from osu!lazer's exports folder. Returns how many were new."""
    directory = exports_dir()
    if not directory.is_dir():
        return 0

    known = {_files_key(stored) for _path, stored in _stored_skins()}
    added = 0
    # Shortest name first, so "skin.osk" wins over its repeat "skin (1).osk".
    for path in sorted(directory.iterdir(), key=lambda path: (len(path.name), path.name)):
        if path.suffix.lower() != ".osk" or not path.is_file():
            continue
        try:
            files = read_cursor_files(path)
            skin_from_files(files, path.stem)
        except (SkinError, zipfile.BadZipFile, OSError):
            continue  # one bad export should not stop the others
        key = _files_key(files)
        if key not in known:
            _store_skin(files, path.stem)
            known.add(key)
            added += 1
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
        raise SkinError("Bu dosya skin listesine ait değil.")
    if path.exists():
        in_use = _files_key(read_cursor_files(path)) == current_skin_key()
        shutil.rmtree(path)
        if in_use:
            reset()


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
        raise SkinError("Bu dosya skin listesine ait değil.")
    name = " ".join(name.split())
    if not name:
        raise SkinError("İsim boş olamaz.")
    if len(name.encode()) > MAX_NAME_BYTES:
        raise SkinError("Bu isim çok uzun.")

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
    return data_dir() / "source"


def _current_source() -> Path | None:
    return next(_source_dir().glob("*.osk"), None)


def _keep_source(files: dict[str, bytes], stem: str) -> None:
    """Keep the cursor files so the size can change without dropping the skin again."""
    shutil.rmtree(_source_dir(), ignore_errors=True)
    _source_dir().mkdir(parents=True)
    _write_archive(_source_dir() / f"{stem}.osk", files)


def apply_skin(path: str | os.PathLike, size: float | None = None) -> Result:
    files = read_cursor_files(path)
    stem = skin_stem(path)
    skin = skin_from_files(files, stem)
    custom_name = _custom_name(path)
    if custom_name:
        skin.name = custom_name

    if size is not None:
        _save_cursor_size(size)
    else:
        size = cursor_size()

    width, height = gameplay_area(*screen_size())
    scale = render.gameplay_scale(width, height, size)
    system_size = int(_interface_get("cursor-size"))

    theme = _write_theme(skin, scale, system_size)
    _write_trail_state(skin, scale, size)
    _keep_source({**files, NAME_ENTRY: custom_name.encode()} if custom_name else files, stem)

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
    source = _current_source()
    custom_name = _custom_name(source) if source else None
    if custom_name:
        return custom_name
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
    if not state.get("skin") or not state.get("trail") or not trail_enabled():
        return None

    info = _extension_info()
    status = info.get("state")
    if status == EXTENSION_STATE_ACTIVE:
        return None
    if status == EXTENSION_STATE_OUT_OF_DATE:
        return "GNOME sürümün değişmiş ve trail eklentisi bu sürümle uyumlu değil. Cursor for osu!'ın güncellenmesi gerekiyor."
    if status == EXTENSION_STATE_ERROR:
        return f"Trail eklentisi çalışamadı: {info.get('error') or 'bilinmeyen hata'}"
    if status in (EXTENSION_STATE_INACTIVE, EXTENSION_STATE_INITIALIZED):
        return "Trail eklentisi kapalı. Eklentiler uygulamasından aç."
    return "Trail'in görünmesi için bir kez oturumu kapatıp tekrar aç."
