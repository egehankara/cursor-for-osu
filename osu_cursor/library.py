"""Shared skin storage and previews for the Linux and Windows frontends."""
from __future__ import annotations

import hashlib
import io
import os
import shutil
import sys
import threading
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from tempfile import TemporaryDirectory

from . import render
from .i18n import _
from .skin import Skin, SkinError, read_cursor_files, skin_from_files, skin_stem

NAME_ENTRY = "display-name.txt"
MAX_NAME_BYTES = 1024
PREVIEW_HEIGHT = 112
PREVIEW_TRAIL_WIDTH = 420
_previews: dict[str, bytes] = {}
_previews_lock = threading.Lock()


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
    author: str = ""


def data_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / "CursorForOsu"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    return Path(base) / "osu-cursor"


def skins_dir() -> Path:
    """Where the skins added in the app are kept, one cursor-only folder each."""
    return data_dir() / "skins"


def _atomic_write(path: Path, data: bytes) -> None:
    # Each writer gets its own temporary file, so two writes can't mix.
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


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


def _preview_png(skin: Skin, key: str) -> bytes:
    with _previews_lock:
        png = _previews.get(key)
    if png is None:
        image = io.BytesIO()
        width = PREVIEW_TRAIL_WIDTH if skin.trail else PREVIEW_HEIGHT
        render.preview(skin, width, PREVIEW_HEIGHT).save(image, "PNG")
        png = image.getvalue()
        with _previews_lock:
            _previews[key] = png
    return png


def library_skins() -> list[LibrarySkin]:
    """The skins added in the app, sorted by name."""
    skins = []
    for path, files in _stored_skins():
        try:
            skin = skin_from_files(files, path.name)
        except SkinError:
            continue
        key = _files_key(files)
        skins.append(
            LibrarySkin(
                path,
                _custom_name(path) or " ".join(skin.name.split()),
                key,
                skin.trail is not None,
                _preview_png(skin, key),
                skin.author,
            )
        )
    # Forget the previews of removed skins.
    with _previews_lock:
        for key in _previews.keys() - {skin.key for skin in skins}:
            del _previews[key]
    return sorted(skins, key=lambda skin: skin.name.casefold())


def skin_key(path: str | os.PathLike) -> str:
    """What add_skin compares, the same for skins whose cursor files are identical."""
    return _files_key(read_cursor_files(path))


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


def _store_skin(files: dict[str, bytes], stem: str) -> None:
    directory = skins_dir()
    directory.mkdir(parents=True, exist_ok=True)
    stem = stem.lstrip(".") or "skin"  # names starting with a dot are skipped as temporary
    if sys.platform == "win32":
        stem = stem[:120].rstrip(" .") or "skin"
        if PureWindowsPath(stem).is_reserved():
            stem = "_" + stem
    target = directory / stem
    number = 2
    while target.exists():
        target = directory / f"{stem} ({number})"
        number += 1

    with TemporaryDirectory(prefix=".skin-", dir=directory) as temporary:
        staged = Path(temporary) / "skin"
        staged.mkdir()
        for name, data in files.items():
            (staged / name).write_bytes(data)
        while True:
            try:
                staged.rename(target)
            except OSError:
                if not target.exists():
                    raise
                target = directory / f"{stem} ({number})"
                number += 1
            else:
                break


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


def library_path(path: str | os.PathLike) -> Path:
    path = Path(path)
    if path.parent != skins_dir() or path.resolve() != skins_dir().resolve() / path.name:
        raise SkinError(_("This file is not part of the skin list."))
    return path


def delete_skin(path: Path) -> None:
    path = library_path(path)
    if path.exists():
        shutil.rmtree(path)


def rename_skin(path: str | os.PathLike, name: str) -> tuple[dict[str, bytes], str]:
    """Give a library skin a new name. The skin's own files stay as they are."""
    path = library_path(path)
    name = " ".join(name.split())
    if not name:
        raise SkinError(_("The name can't be empty."))
    if len(name.encode()) > MAX_NAME_BYTES:
        raise SkinError(_("This name is too long."))

    files = read_cursor_files(path)
    _atomic_write(path / NAME_ENTRY, name.encode())

    return files, name
