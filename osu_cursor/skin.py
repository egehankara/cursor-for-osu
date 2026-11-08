"""Read the cursor parts of an osu! skin from an .osk archive or a folder.

Skins are untrusted downloads, so archives are never extracted to disk. Only the
few files we need are read into memory, and each one has a size limit.
"""

from __future__ import annotations

import io
import posixpath
import zipfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_IMAGE_SIDE = 4096


class SkinError(Exception):
    """The skin cannot be used. The message is shown to the user."""


@dataclass
class Sprite:
    image: Image.Image  # always RGBA
    scale_adjust: int  # 2 for @2x textures, otherwise 1

    @property
    def display_size(self) -> tuple[float, float]:
        return self.image.width / self.scale_adjust, self.image.height / self.scale_adjust


@dataclass
class Skin:
    name: str
    cursor: Sprite
    middle: Sprite | None
    trail: Sprite | None
    cursor_centre: bool
    cursor_rotate: bool
    cursor_trail_rotate: bool

    @property
    def disjoint_trail(self) -> bool:
        """Skins without cursormiddle use separate, stamped trail sprites."""
        return self.middle is None


def read_cursor_files(path: str | Path) -> dict[str, bytes]:
    """Return the skin files we use, keyed by lowercase name."""
    path = Path(path)
    if not path.exists():
        raise SkinError(f"{path} bulunamadı.")

    if path.is_dir():
        files = {}
        for entry in path.iterdir():
            name = entry.name.lower()
            if _is_wanted(name) and entry.is_file() and entry.stat().st_size <= MAX_FILE_BYTES:
                files[name] = entry.read_bytes()
        return files

    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as error:
        raise SkinError(f"{path.name} geçerli bir .osk dosyası değil.") from error

    with archive:
        folders: dict[str, dict[str, zipfile.ZipInfo]] = {}
        for info in archive.infolist():
            if info.is_dir():
                continue
            folder, name = posixpath.split(info.filename.replace("\\", "/"))
            folders.setdefault(folder, {})[name.lower()] = info

        # Some skins are zipped with an extra parent folder around them.
        candidates = [f for f, names in folders.items() if _has_cursor(names)]
        if not candidates:
            raise SkinError("Bu skin'de cursor.png yok.")
        chosen = folders[min(candidates, key=lambda f: (f.count("/"), f))]

        files = {}
        for name, info in chosen.items():
            if _is_wanted(name) and info.file_size <= MAX_FILE_BYTES:
                with archive.open(info) as handle:
                    files[name] = handle.read(MAX_FILE_BYTES + 1)
        return files


def _has_cursor(names) -> bool:
    return "cursor.png" in names or "cursor@2x.png" in names


def _is_wanted(name: str) -> bool:
    return name == "skin.ini" or (
        name.startswith(("cursor.", "cursor@2x.", "cursormiddle", "cursortrail"))
    )


def _decode(data: bytes) -> Image.Image | None:
    if len(data) > MAX_FILE_BYTES:
        return None
    try:
        image = Image.open(io.BytesIO(data))
        if max(image.size) > MAX_IMAGE_SIDE:
            return None
        return image.convert("RGBA")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return None


def _sprite(files: dict[str, bytes], name: str) -> Sprite | None:
    """Load a texture, preferring @2x like the game does."""
    for suffix, scale_adjust in (("@2x", 2), ("", 1)):
        data = files.get(f"{name}{suffix}.png")
        if data is not None:
            image = _decode(data)
            if image is not None:
                return Sprite(image, scale_adjust)
    return None


def parse_general(data: bytes) -> dict[str, str]:
    """Return the [General] section of a skin.ini."""
    values: dict[str, str] = {}
    section = None
    for raw_line in data.decode("utf-8-sig", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
        elif section == "general" and ":" in line:
            key, value = line.split(":", 1)
            values[key.strip().lower()] = value.split("//", 1)[0].strip()
    return values


def _flag(general: dict[str, str], key: str, default: bool = True) -> bool:
    value = general.get(key.lower())
    if value is None:
        return default
    return value.lower() in ("1", "true")


def _visible(sprite: Sprite | None) -> Sprite | None:
    """Skins turn the trail off with a fully transparent texture."""
    if sprite is None or sprite.image.getextrema()[3][1] == 0:
        return None
    return sprite


def skin_from_files(files: dict[str, bytes], fallback_name: str) -> Skin:
    cursor = _sprite(files, "cursor")
    if cursor is None:
        raise SkinError("Bu skin'de okunabilir bir cursor.png yok.")

    general = parse_general(files["skin.ini"]) if "skin.ini" in files else {}
    return Skin(
        name=general.get("name") or fallback_name,
        cursor=cursor,
        middle=_sprite(files, "cursormiddle"),
        trail=_visible(_sprite(files, "cursortrail")),
        cursor_centre=_flag(general, "CursorCentre"),
        cursor_rotate=_flag(general, "CursorRotate"),
        cursor_trail_rotate=_flag(general, "CursorTrailRotate"),
    )


def load_skin(path: str | Path) -> Skin:
    return skin_from_files(read_cursor_files(path), Path(path).stem)
