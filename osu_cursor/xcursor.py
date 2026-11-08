"""Write Xcursor files, the cursor image format every Linux desktop reads."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from PIL import Image

_MAGIC = b"Xcur"
_FILE_HEADER_SIZE = 16
_FILE_VERSION = 0x0001_0000
_TOC_ENTRY_SIZE = 12
_IMAGE_TYPE = 0xFFFD_0002
_IMAGE_HEADER_SIZE = 36
_IMAGE_VERSION = 1


@dataclass
class Frame:
    image: Image.Image  # premultiplied, mode "RGBa"
    hot_x: int
    hot_y: int
    delay_ms: int = 0


def _bgra_bytes(image: Image.Image) -> bytes:
    """Xcursor stores premultiplied ARGB32, which is B, G, R, A in file order."""
    rgba = image.tobytes()
    pixels = bytearray(rgba)
    pixels[0::4] = rgba[2::4]
    pixels[2::4] = rgba[0::4]
    return bytes(pixels)


def encode(frames: list[Frame], nominal_size: int) -> bytes:
    table_size = len(frames) * _TOC_ENTRY_SIZE
    position = _FILE_HEADER_SIZE + table_size

    table = bytearray()
    chunks = bytearray()
    for frame in frames:
        width, height = frame.image.size
        table += struct.pack("<III", _IMAGE_TYPE, nominal_size, position)
        chunk = struct.pack(
            "<IIIIIIIII",
            _IMAGE_HEADER_SIZE,
            _IMAGE_TYPE,
            nominal_size,
            _IMAGE_VERSION,
            width,
            height,
            frame.hot_x,
            frame.hot_y,
            frame.delay_ms,
        )
        chunks += chunk + _bgra_bytes(frame.image)
        position += len(chunk) + width * height * 4

    header = _MAGIC + struct.pack("<III", _FILE_HEADER_SIZE, _FILE_VERSION, len(frames))
    return header + bytes(table) + bytes(chunks)
