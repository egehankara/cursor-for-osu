"""System cursor shapes kept beside the skin cursor, coloured like the skin.

Text, resize, move and similar cursors tell you what a click will do, so they can
be taken from the cursor theme used before the skin. They get the skin's colour:
the dark parts of the original take a dark shade of it and the light parts a
light shade, so the outline stays clear on any background.
"""

from __future__ import annotations

import colorsys
import os
from pathlib import Path

from PIL import Image

from . import xcursor
from .xcursor import Frame

# Names that show the same shape, the first one found in the theme is used for all.
SHAPES = [
    "text xterm ibeam",
    "vertical-text",
    "crosshair cross tcross",
    "cell plus",
    "not-allowed forbidden crossed_circle circle",
    "no-drop dnd-no-drop",
    "all-scroll size_all fleur all-resize",
    "e-resize right_side",
    "w-resize left_side",
    "n-resize top_side",
    "s-resize bottom_side",
    "ne-resize top_right_corner",
    "nw-resize top_left_corner",
    "se-resize bottom_right_corner",
    "sw-resize bottom_left_corner",
    "ew-resize h_double_arrow sb_h_double_arrow size_hor",
    "ns-resize v_double_arrow sb_v_double_arrow size_ver",
    "nesw-resize fd_double_arrow size_bdiag",
    "nwse-resize bd_double_arrow size_fdiag",
    "col-resize split_h",
    "row-resize split_v",
]
# Used when a theme has no picture of its own for a shape.
FALLBACKS = {
    "vertical-text": "text",
    "no-drop": "not-allowed",
    "col-resize": "ew-resize",
    "row-resize": "ns-resize",
}
FALLBACK_THEME = "Adwaita"
MAX_INHERITS = 10
MAX_FILE_BYTES = 16 * 1024 * 1024
DARK_LIGHTNESS = 0.18
LIGHT_LIGHTNESS = 0.88
MAX_SATURATION = 0.9
GREY_SATURATION = 0.15  # cursors paler than this on average are treated as grey
HUE_BINS = 12


def _icon_dirs() -> list[Path]:
    """Where cursor themes are looked up, in the same order as the desktop does."""
    data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    return [
        Path.home() / ".icons",
        Path(data_home) / "icons",
        *(Path(folder) / "icons" for folder in data_dirs.split(":") if folder),
    ]


def _inherits(theme: str) -> list[str]:
    for folder in _icon_dirs():
        index = folder / theme / "index.theme"
        try:
            lines = index.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            key, _, value = line.partition("=")
            if key.strip() == "Inherits":
                return [name.strip() for name in value.split(",") if name.strip()]
        return []
    return []


def _themes(theme: str) -> list[str]:
    """The theme followed by the ones it inherits from, nearest first."""
    order, waiting = [], [theme]
    while waiting and len(order) < MAX_INHERITS:
        name = waiting.pop(0)
        if name in order or "/" in name or name in ("", ".", ".."):
            continue
        order.append(name)
        waiting.extend(_inherits(name))
    return order


def _find(themes: list[str], names: list[str]) -> Path | None:
    for theme in themes:
        for folder in _icon_dirs():
            cursors = folder / theme / "cursors"
            for name in names:
                path = cursors / name
                if path.is_file():
                    return path
    return None


def _arrow(themes: list[str]) -> Path | None:
    path = _find(themes, ["default", "left_ptr", "arrow"])
    return path.resolve() if path else None


def skin_colour(image: Image.Image) -> tuple[float, float]:
    """Hue and saturation of the colour most of the cursor is painted in."""
    small = image.convert("RGBA")
    small.thumbnail((64, 64))
    weights = [0.0] * HUE_BINS
    hues = [[0.0, 0.0] for _ in range(HUE_BINS)]  # weighted sums for an average inside a bin
    saturations = [0.0] * HUE_BINS
    seen = 0
    pixels = small.tobytes()
    for index in range(0, len(pixels), 4):
        red, green, blue, alpha = pixels[index : index + 4]
        if alpha < 128:
            continue
        seen += 1
        hue, lightness, saturation = colorsys.rgb_to_hls(red / 255, green / 255, blue / 255)
        # Near-black and near-white pixels say little about the colour.
        weight = saturation * min(lightness, 1 - lightness) * 2
        if weight <= 0:
            continue
        bin_ = min(int(hue * HUE_BINS), HUE_BINS - 1)
        weights[bin_] += weight
        hues[bin_][0] += hue * weight
        hues[bin_][1] += weight
        saturations[bin_] += saturation * weight
    if not seen or sum(weights) / seen < GREY_SATURATION:
        return 0.0, 0.0
    best = max(range(HUE_BINS), key=weights.__getitem__)
    return hues[best][0] / hues[best][1], min(saturations[best] / weights[best], MAX_SATURATION)


def tint(image: Image.Image, hue: float, saturation: float) -> Image.Image:
    """Repaint a premultiplied cursor image from dark to light shades of one colour."""
    dark = colorsys.hls_to_rgb(hue, DARK_LIGHTNESS, saturation)
    light = colorsys.hls_to_rgb(hue, LIGHT_LIGHTNESS, saturation)
    straight = image.convert("RGBA")
    lightness = straight.convert("L")
    channels = [
        lightness.point(lambda value, low=low, high=high: round((low + (high - low) * value / 255) * 255))
        for low, high in zip(dark, light)
    ]
    return Image.merge("RGBA", (*channels, straight.getchannel("A"))).convert("RGBa")


def write_shapes(cursors: Path, theme: str, colour: tuple[float, float]) -> list[str]:
    """Write tinted copies of the theme's shapes into a cursors folder. Returns the names written.

    Shapes the theme draws with its plain arrow are skipped, they keep the skin cursor.
    """
    themes = _themes(theme)
    if FALLBACK_THEME not in themes:
        themes.append(FALLBACK_THEME)
    arrow = _arrow(themes)
    written = {}
    for shape in SHAPES:
        names = shape.split()
        source = _find(themes, names)
        if source is None and names[0] in FALLBACKS:
            source = _find(themes, [FALLBACKS[names[0]]])
        if source is None or source.resolve() == arrow:
            continue
        try:
            if source.stat().st_size > MAX_FILE_BYTES:
                continue
            images = xcursor.decode(source.read_bytes())
        except (OSError, ValueError):
            continue  # this shape keeps the skin cursor
        if not images:
            continue
        tinted = [
            (size, Frame(tint(frame.image, *colour), frame.hot_x, frame.hot_y, frame.delay_ms))
            for size, frame in images
        ]
        main = cursors / names[0]
        main.unlink(missing_ok=True)
        main.write_bytes(xcursor.encode_sized(tinted))
        for alias in names[1:]:
            link = cursors / alias
            link.unlink(missing_ok=True)
            link.symlink_to(names[0])
        written.update(dict.fromkeys(names))
    return list(written)
