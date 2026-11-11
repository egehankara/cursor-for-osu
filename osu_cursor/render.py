"""Turn a skin into cursor frames sized the way the game shows them.

The numbers follow osu!lazer's LegacyCursor and NonPlayfieldSprite
(Copyright (c) ppy Pty Ltd, MIT Licence).
"""

from __future__ import annotations

from PIL import Image, ImageChops

from .i18n import _
from .skin import Skin, SkinError, Sprite
from .xcursor import Frame

MAX_CURSOR_BYTES = 128 * 1024 * 1024
TRAIL_INTERVAL_DIVISOR = 2.5
PREVIEW_DISJOINT_PARTS = 9  # how many stamped parts are alive during their 150 ms fade


def gameplay_scale(screen_width: float, screen_height: float, cursor_size: float) -> float:
    """Screen pixels per texture pixel of a non-@2x skin element during gameplay."""
    return min(screen_height, screen_width * 3 / 4) / 768 * cursor_size


def _scaled_size(sprite: Sprite, scale: float) -> tuple[int, int]:
    width, height = sprite.display_size
    return max(1, round(width * scale)), max(1, round(height * scale))


def _scaled(sprite: Sprite, scale: float) -> Image.Image:
    """Resize in premultiplied alpha so transparent edges don't pick up dark fringes."""
    return sprite.image.convert("RGBa").resize(_scaled_size(sprite, scale), Image.Resampling.LANCZOS)


def _origin(size: tuple[int, int], centre: bool) -> tuple[float, float]:
    return (size[0] / 2, size[1] / 2) if centre else (0.0, 0.0)


def _visible_size(sprite: Sprite) -> float:
    """The longest side of the part of a texture that can be seen, in display units."""
    box = sprite.image.getchannel("A").getbbox()
    if box is None:
        return max(sprite.display_size)
    return max(box[2] - box[0], box[3] - box[1]) / sprite.scale_adjust


def _placed(
    layer: Image.Image, size: tuple[int, int], point: tuple[float, float], centre: bool
) -> Image.Image:
    """A canvas-sized picture with the layer's origin on the point."""
    origin = _origin(layer.size, centre)
    canvas = Image.new("RGBA", size)
    canvas.paste(layer, (round(point[0] - origin[0]), round(point[1] - origin[1])))
    return canvas


def _faded(image: Image.Image, alpha: float) -> Image.Image:
    faded = image.copy()
    faded.putalpha(image.getchannel("A").point(lambda value: round(value * alpha)))
    return faded


def _draw_preview_trail(
    canvas: Image.Image, skin: Skin, scale: float, point: tuple[float, float], span: float
) -> Image.Image:
    """Lay the trail out to the left of the cursor, older parts further away and fainter."""
    trail = _scaled(skin.trail, scale).convert("RGBA")

    if skin.disjoint_trail:
        last = PREVIEW_DISJOINT_PARTS - 1
        for part in range(last, -1, -1):
            x = point[0] - span * part / last
            layer = _placed(trail, canvas.size, (x, point[1]), skin.cursor_centre)
            canvas = Image.alpha_composite(canvas, _faded(layer, 1 - part / PREVIEW_DISJOINT_PARTS))
        return canvas

    interval = max(trail.width / TRAIL_INTERVAL_DIVISOR, 0.5)
    canvas = canvas.convert("RGBa")
    for part in range(int(span / interval), 0, -1):
        distance = part * interval
        layer = _placed(trail, canvas.size, (point[0] - distance, point[1]), True)
        canvas = ImageChops.add(canvas, _faded(layer, 1 - distance / span).convert("RGBa"))
    return canvas.convert("RGBA")


def preview(skin: Skin, width: int, height: int) -> Image.Image:
    """A picture of the cursor moving right, with its trail behind it."""
    sprites = [sprite for sprite in (skin.cursor, skin.middle, skin.trail) if sprite]
    scale = height / max(_visible_size(sprite) for sprite in sprites)
    size = (width, height)
    cursor = _scaled(skin.cursor, scale).convert("RGBA")

    point = (width - height / 2, height / 2)
    if not skin.cursor_centre:
        point = (point[0] - cursor.width / 2, point[1] - cursor.height / 2)

    canvas = Image.new("RGBA", size)
    if skin.trail:
        canvas = _draw_preview_trail(canvas, skin, scale, point, width - height)
    canvas = Image.alpha_composite(canvas, _placed(cursor, size, point, skin.cursor_centre))
    if skin.middle:
        middle = _scaled(skin.middle, scale).convert("RGBA")
        canvas = Image.alpha_composite(canvas, _placed(middle, size, point, skin.cursor_centre))
    return canvas


def build_frames(skin: Skin, scale: float) -> list[Frame]:
    """One still frame, cut down to the visible part of the cursor."""
    # Measured first, so a huge cursor is refused before any memory is used.
    sizes = [_scaled_size(sprite, scale) for sprite in (skin.cursor, skin.middle) if sprite]
    if max(width * height * 4 for width, height in sizes) > MAX_CURSOR_BYTES:
        raise SkinError(_("This skin's cursor is too large at this size. Make the cursor size smaller and try again."))

    width = max(size[0] for size in sizes)
    height = max(size[1] for size in sizes)
    origin = _origin((width, height), skin.cursor_centre)
    hot_x, hot_y = round(origin[0]), round(origin[1])

    image = Image.new("RGBa", (width, height))
    cursor = _scaled(skin.cursor, scale)
    cursor_origin = _origin(cursor.size, skin.cursor_centre)
    image.paste(cursor, (hot_x - round(cursor_origin[0]), hot_y - round(cursor_origin[1])))
    if skin.middle:
        middle = _scaled(skin.middle, scale).convert("RGBA")
        middle_origin = _origin(middle.size, skin.cursor_centre)
        overlay = Image.new("RGBA", (width, height))
        overlay.paste(middle, (hot_x - round(middle_origin[0]), hot_y - round(middle_origin[1])))
        image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGBa")

    # The hotspot has to stay inside the image or the cursor file is rejected.
    box = image.getchannel("a").getbbox() or (hot_x, hot_y, hot_x, hot_y)
    left, top = min(box[0], hot_x), min(box[1], hot_y)
    right, bottom = max(box[2], hot_x + 1), max(box[3], hot_y + 1)
    return [Frame(image.crop((left, top, right, bottom)), hot_x - left, hot_y - top)]
