"""Turn a skin into cursor frames sized the way the game shows them.

The numbers follow osu!lazer's LegacyCursor and NonPlayfieldSprite
(Copyright (c) ppy Pty Ltd, MIT Licence).
"""

from __future__ import annotations

import math

from PIL import Image

from .skin import Skin, Sprite
from .xcursor import Frame

REVOLUTION_MS = 10_000
SPIN_FRAMES = 120


def gameplay_scale(screen_width: int, screen_height: int, cursor_size: float) -> float:
    """Screen pixels per texture pixel of a non-@2x skin element during gameplay."""
    return min(screen_height, screen_width * 3 / 4) / 768 * cursor_size


def _scaled(sprite: Sprite, scale: float) -> Image.Image:
    """Resize in premultiplied alpha so transparent edges don't pick up dark fringes."""
    width, height = sprite.display_size
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return sprite.image.convert("RGBa").resize(size, Image.Resampling.LANCZOS)


def _origin(image: Image.Image, centre: bool) -> tuple[float, float]:
    return (image.width / 2, image.height / 2) if centre else (0.0, 0.0)


def _radius(image: Image.Image, origin: tuple[float, float]) -> int:
    corners = ((0, 0), (image.width, 0), (0, image.height), (image.width, image.height))
    return math.ceil(max(math.dist(origin, corner) for corner in corners))


def build_frames(skin: Skin, scale: float) -> list[Frame]:
    cursor = _scaled(skin.cursor, scale)
    middle = _scaled(skin.middle, scale) if skin.middle else None

    origin = _origin(cursor, skin.cursor_centre)
    middle_origin = _origin(middle, skin.cursor_centre) if middle else origin
    radius = _radius(cursor, origin)
    if middle:
        radius = max(radius, _radius(middle, middle_origin))

    # Everything is laid out around the hotspot in the middle of a square canvas,
    # which leaves room for the cursor at any rotation.
    side = radius * 2
    canvas = Image.new("RGBa", (side, side))
    canvas.paste(cursor, (round(radius - origin[0]), round(radius - origin[1])))

    overlay = None
    if middle:
        overlay = Image.new("RGBA", (side, side))
        overlay.paste(
            middle.convert("RGBA"),
            (round(radius - middle_origin[0]), round(radius - middle_origin[1])),
        )

    count = SPIN_FRAMES if skin.cursor_rotate else 1
    delay = round(REVOLUTION_MS / SPIN_FRAMES) if skin.cursor_rotate else 0

    frames = []
    for index in range(count):
        # PIL rotates counter-clockwise, the game spins clockwise.
        image = canvas.rotate(
            -360 * index / count, Image.Resampling.BICUBIC, center=(radius, radius)
        )
        if overlay is not None:
            image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGBa")
        frames.append(Frame(image, radius, radius, delay))
    return frames
