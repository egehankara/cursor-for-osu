"""Win32 cursor and premultiplied bitmap operations."""
from __future__ import annotations

import ctypes as c
import hashlib
import struct
from contextlib import contextmanager
from ctypes import wintypes as w

user = c.WinDLL("user32", use_last_error=True)
gdi = c.WinDLL("gdi32", use_last_error=True)
H = w.HANDLE


def bind(dll, name, result, *arguments):
    function = getattr(dll, name)
    function.restype = result
    function.argtypes = arguments
    return function


class Icon(c.Structure):
    _fields_ = [("icon", w.BOOL), ("x", w.DWORD), ("y", w.DWORD), ("mask", H), ("color", H)]


class Bitmap(c.Structure):
    _fields_ = [("kind", w.LONG), ("width", w.LONG), ("height", w.LONG), ("stride", w.LONG),
                ("planes", w.WORD), ("depth", w.WORD), ("bits", c.c_void_p)]


class CursorInfo(c.Structure):
    _fields_ = [("size", w.DWORD), ("flags", w.DWORD), ("cursor", H), ("point", w.POINT)]


create_icon = bind(user, "CreateIconIndirect", H, c.POINTER(Icon))
get_icon = bind(user, "GetIconInfo", w.BOOL, H, c.POINTER(Icon))
destroy_cursor = bind(user, "DestroyCursor", w.BOOL, H)
load_cursor = bind(user, "LoadCursorW", H, H, c.c_void_p)
set_cursor = bind(user, "SetSystemCursor", w.BOOL, H, w.DWORD)
system_parameters = bind(user, "SystemParametersInfoW", w.BOOL, w.UINT, w.UINT, c.c_void_p, w.UINT)
get_cursor = bind(user, "GetCursorInfo", w.BOOL, c.POINTER(CursorInfo))
draw_icon = bind(user, "DrawIconEx", w.BOOL, H, c.c_int, c.c_int, H, c.c_int, c.c_int, w.UINT, H, w.UINT)
create_dc = bind(gdi, "CreateCompatibleDC", H, H)
delete_dc = bind(gdi, "DeleteDC", w.BOOL, H)
select_object = bind(gdi, "SelectObject", H, H, H)
delete_object = bind(gdi, "DeleteObject", w.BOOL, H)
create_dib = bind(gdi, "CreateDIBSection", H, H, c.c_void_p, w.UINT, c.POINTER(c.c_void_p), H, w.DWORD)
create_bitmap = bind(gdi, "CreateBitmap", H, c.c_int, c.c_int, w.UINT, w.UINT, c.c_void_p)
get_object = bind(gdi, "GetObjectW", c.c_int, H, c.c_int, c.c_void_p)
get_metrics = bind(user, "GetSystemMetrics", c.c_int, c.c_int)
set_dpi_context = bind(user, "SetProcessDpiAwarenessContext", w.BOOL, H)
ARROW = 32512
# Text, link, resize and move. Busy and unavailable stay distinct in both modes.
SHAPES = (ARROW, 32513, 32649, 32642, 32643, 32644, 32645, 32646)


def checked(value):
    if not value:
        raise c.WinError(c.get_last_error())
    return value


@contextmanager
def dib(width, height):
    header = c.create_string_buffer(struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 32, 0, 0, 0, 0, 0, 0))
    data = c.c_void_p()
    bitmap = checked(create_dib(None, header, 0, c.byref(data), None, 0))
    try:
        yield bitmap, data
    finally:
        delete_object(bitmap)


@contextmanager
def surface(width, height):
    dc = checked(create_dc(None))
    try:
        with dib(width, height) as (bitmap, data):
            previous = checked(select_object(dc, bitmap))
            try:
                yield dc, bitmap, data
            finally:
                select_object(dc, previous)
    finally:
        delete_dc(dc)


def bgra(image):
    return image.tobytes("raw", "BGRA")


def frame_bytes(frame):
    from PIL import Image

    # Keep the premultiplied channels produced by render.build_frames.
    return bgra(Image.merge("RGBA", frame.image.split()))


def create_cursor(frame):
    width, height = frame.image.size
    mask_data = bytes(((width + 15) // 16) * 2 * height)
    with dib(width, height) as (bitmap, data):
        c.memmove(data, frame_bytes(frame), width * height * 4)
        mask = checked(create_bitmap(width, height, 1, 1, mask_data))
        try:
            return checked(create_icon(c.byref(Icon(False, frame.hot_x, frame.hot_y, mask, bitmap))))
        finally:
            delete_object(mask)


def fingerprint(cursor):
    info = Icon()
    checked(get_icon(cursor, c.byref(info)))
    try:
        dimensions = Bitmap()
        checked(get_object(info.color or info.mask, c.sizeof(dimensions), c.byref(dimensions)))
        width, height = dimensions.width, dimensions.height // (1 if info.color else 2)
        if not (0 < width <= 1024 and 0 < height <= 1024):
            return None
        with surface(width, height) as (dc, _bitmap, data):
            c.memset(data, 0, width * height * 4)
            checked(draw_icon(dc, 0, 0, cursor, width, height, 0, None, 3))
            pixels = c.string_at(data, width * height * 4)
        return hashlib.sha256(struct.pack("<4I", width, height, info.x, info.y) + pixels).hexdigest()
    finally:
        if info.color:
            delete_object(info.color)
        if info.mask:
            delete_object(info.mask)


def stock_cursor(role):
    return checked(load_cursor(None, role))


def reset():
    checked(system_parameters(0x57, 0, None, 0))


def replace(frame, roles, clear_old):
    handles = []
    try:
        for _role in roles:
            handles.append(create_cursor(frame))
        if clear_old:
            reset()
        for role in roles:
            checked(set_cursor(handles[0], role))
            handles.pop(0)
        return fingerprint(stock_cursor(ARROW))
    finally:
        for handle in handles:
            destroy_cursor(handle)
