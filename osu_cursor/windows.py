"""Apply Windows cursor skins and track which one owns the current cursor."""
from __future__ import annotations

import json
import math
import msvcrt
from contextlib import contextmanager
from pathlib import Path

from . import library, render, win32
from .i18n import _
from .library import Result, data_dir
from .skin import SkinError, read_cursor_files, skin_from_files, skin_stem

TRAIL_DENSITY_MIN, TRAIL_DENSITY_MAX = 50, 400


def _read(name: str) -> dict:
    try:
        value = json.loads((data_dir() / name).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(name: str, value: dict) -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    library._atomic_write(data_dir() / name, json.dumps(value).encode("utf-8"))


@contextmanager
def _lock():
    data_dir().mkdir(parents=True, exist_ok=True)
    with (data_dir() / "cursor.lock").open("a+b") as lock:
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def _source() -> Path:
    return data_dir() / "active.osk"


def active() -> dict:
    state = _read("active.json")
    if not state.get("fingerprint") or not _source().is_file():
        return {}
    try:
        return state if win32.fingerprint(win32.stock_cursor(win32.ARROW)) == state["fingerprint"] else {}
    except OSError:
        return {}


def cursor_size() -> float:
    size = _read("settings.json").get("cursor_size", 1.0)
    return size if isinstance(size, (int, float)) and 0.1 <= size <= 2.0 else 1.0


def keep_system_cursors() -> bool:
    return _read("settings.json").get("keep_system_cursors", True) is not False


def trail_enabled() -> bool:
    return _read("settings.json").get("trail_enabled", True) is not False


def trail_density() -> int:
    density = _read("settings.json").get("trail_density", 100)
    return density if type(density) is int and TRAIL_DENSITY_MIN <= density <= TRAIL_DENSITY_MAX else 100


def _forget() -> None:
    (data_dir() / "active.json").unlink(missing_ok=True)
    _source().unlink(missing_ok=True)


def _validate_size(size: float) -> None:
    if not math.isfinite(size) or not 0.1 <= size <= 2.0:
        raise SkinError(_("The size has to be between {low} and {high}.").format(low=0.1, high=2.0))


def _apply(path, size: float, keep: bool) -> Result:
    _validate_size(size)
    files = read_cursor_files(path)
    previous = active()
    custom_name = previous.get("name") if Path(path) == _source() else library._custom_name(path)
    skin = skin_from_files(files, skin_stem(path))
    name = custom_name or " ".join(skin.name.split())
    width, height = win32.get_metrics(0), win32.get_metrics(1)
    scale = render.gameplay_scale(width, height, size)
    frame = render.build_frames(skin, scale)[0]
    if max(frame.image.size) > 1024:
        raise SkinError(_("This skin's cursor is too large at this size. Make the cursor size smaller and try again."))
    roles = (win32.ARROW,) if keep else win32.SHAPES
    try:
        fingerprint = win32.replace(frame, roles, bool(previous and previous.get("keep") != keep))
        if not fingerprint:
            raise OSError("The system cursor could not be read after applying it.")
        library._write_archive(_source(), files)
        _write("active.json", dict(fingerprint=fingerprint, key=library._files_key(files),
                                   name=name, scale=scale, keep=keep))
        _write("settings.json", {**_read("settings.json"), "cursor_size": size, "keep_system_cursors": keep})
    except OSError:
        # A batch may have replaced only some of its cursors.
        win32.reset()
        _forget()
        raise
    return Result(name, skin.trail is not None, False, frame.image.width)


def apply_skin(path, size: float | None = None) -> Result:
    with _lock():
        return _apply(path, cursor_size() if size is None else size, keep_system_cursors())


def set_cursor_size(size: float) -> Result | None:
    with _lock():
        if active():
            return _apply(_source(), size, keep_system_cursors())
        _validate_size(size)
        _write("settings.json", {**_read("settings.json"), "cursor_size": size})
        return None


def set_keep_system_cursors(keep: bool) -> None:
    with _lock():
        if active():
            _apply(_source(), cursor_size(), keep)
        else:
            _write("settings.json", {**_read("settings.json"), "keep_system_cursors": keep})


def set_trail_enabled(enabled: bool) -> None:
    with _lock():
        _write("settings.json", {**_read("settings.json"), "trail_enabled": enabled})


def set_trail_density(density: int) -> None:
    with _lock():
        _write("settings.json", {**_read("settings.json"), "trail_density": density})


def reset() -> None:
    with _lock():
        win32.reset()
        _forget()


def remove_skin(path) -> None:
    with _lock():
        path = library.library_path(path)
        if active().get("key") == library.skin_key(path):
            win32.reset()
            _forget()
        library.delete_skin(path)


def rename_skin(path, name) -> None:
    with _lock():
        files, name = library.rename_skin(path, name)
        current = active()
        if current.get("key") == library._files_key(files):
            _write("active.json", {**current, "name": name})


def trail_skin(state: dict):
    if state and trail_enabled():
        return skin_from_files(read_cursor_files(_source()), state["name"])
    return None
