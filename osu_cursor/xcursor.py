"""Read and write Xcursor files, the cursor image format every Linux desktop reads."""

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
MAX_SIDE = 1024  # larger images are refused when reading, cursor themes stay far below
MAX_IMAGES = 4096


@dataclass
class Frame:
    image: Image.Image  # premultiplied, mode "RGBa"
    hot_x: int
    hot_y: int
    delay_ms: int = 0


def _swap_red_blue(pixels: bytes) -> bytes:
    """Xcursor stores premultiplied ARGB32, which is B, G, R, A in file order."""
    swapped = bytearray(pixels)
    swapped[0::4] = pixels[2::4]
    swapped[2::4] = pixels[0::4]
    return bytes(swapped)


def encode(frames: list[Frame], nominal_size: int) -> bytes:
    return encode_sized([(nominal_size, frame) for frame in frames])


def encode_sized(images: list[tuple[int, Frame]]) -> bytes:
    """Write images that each have their own nominal size, as cursor themes do."""
    table_size = len(images) * _TOC_ENTRY_SIZE
    position = _FILE_HEADER_SIZE + table_size

    table = bytearray()
    chunks = bytearray()
    for nominal_size, frame in images:
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
        chunks += chunk + _swap_red_blue(frame.image.tobytes())
        position += len(chunk) + width * height * 4

    header = _MAGIC + struct.pack("<III", _FILE_HEADER_SIZE, _FILE_VERSION, len(images))
    return header + bytes(table) + bytes(chunks)


def decode(data: bytes) -> list[tuple[int, Frame]]:
    """The images of an Xcursor file with their nominal sizes. Raises ValueError if it is broken."""
    try:
        magic, header_size, _version, count = struct.unpack_from("<4sIII", data)
        if magic != _MAGIC or count > MAX_IMAGES:
            raise ValueError("not an Xcursor file")
        images = []
        for index in range(count):
            kind, nominal_size, position = struct.unpack_from(
                "<III", data, header_size + index * _TOC_ENTRY_SIZE
            )
            if kind != _IMAGE_TYPE:
                continue  # comments
            fields = struct.unpack_from("<IIIIIIIII", data, position)
            chunk_size, _kind, _nominal, _image_version, width, height, hot_x, hot_y, delay = fields
            if not (0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE):
                raise ValueError("cursor image too large")
            start = position + chunk_size
            pixels = data[start : start + width * height * 4]
            if len(pixels) != width * height * 4:
                raise ValueError("cursor image cut short")
            image = Image.frombytes("RGBa", (width, height), _swap_red_blue(pixels))
            images.append((nominal_size, Frame(image, min(hot_x, width - 1), min(hot_y, height - 1), delay)))
    except struct.error as error:
        raise ValueError("cursor file cut short") from error
    return images

