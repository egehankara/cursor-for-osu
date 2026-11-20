"""Draw a small click-through cursor trail in the Windows compositor."""
from __future__ import annotations

import ctypes as c
import math
import time
from collections import deque
from ctypes import wintypes as w

from PySide6.QtCore import QAbstractNativeEventFilter, QRect, QTimer, Qt
from PySide6.QtGui import QImage, QPainter

from . import render, win32

H = win32.H
bind = win32.bind
user = win32.user
MAX_PARTS = 256


class RawDevice(c.Structure):
    _fields_ = [("page", w.USHORT), ("usage", w.USHORT), ("flags", w.DWORD), ("window", H)]


class Blend(c.Structure):
    _fields_ = [("operation", w.BYTE), ("flags", w.BYTE), ("opacity", w.BYTE), ("alpha", w.BYTE)]


monitor_callback = c.WINFUNCTYPE(w.BOOL, H, H, c.POINTER(w.RECT), w.LPARAM)
enum_monitors = bind(user, "EnumDisplayMonitors", w.BOOL, H, c.POINTER(w.RECT), monitor_callback, w.LPARAM)
register_raw = bind(user, "RegisterRawInputDevices", w.BOOL, c.POINTER(RawDevice), w.UINT, w.UINT)
create_window = bind(user, "CreateWindowExW", H, w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
                     c.c_int, c.c_int, c.c_int, c.c_int, H, H, H, c.c_void_p)
destroy_window = bind(user, "DestroyWindow", w.BOOL, H)
show_window = bind(user, "ShowWindow", w.BOOL, H, c.c_int)
get_window = bind(user, "GetWindow", H, H, w.UINT)
set_window_pos = bind(user, "SetWindowPos", w.BOOL, H, H, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT)
present = bind(user, "UpdateLayeredWindow", w.BOOL, H, H, c.POINTER(w.POINT), c.POINTER(w.SIZE), H,
               c.POINTER(w.POINT), w.DWORD, c.POINTER(Blend), w.DWORD)
foreground = bind(user, "GetForegroundWindow", H)
window_at_point = bind(user, "WindowFromPoint", H, w.POINT)
root_window = bind(user, "GetAncestor", H, H, w.UINT)
window_rect = bind(user, "GetWindowRect", w.BOOL, H, c.POINTER(w.RECT))
window_class = bind(user, "GetClassNameW", c.c_int, H, w.LPWSTR, c.c_int)
is_maximized = bind(user, "IsZoomed", w.BOOL, H)
window_style = bind(user, "GetWindowLongW", w.LONG, H, c.c_int)
dwm_bounds = bind(c.WinDLL("dwmapi"), "DwmGetWindowAttribute", w.LONG, H, w.DWORD, c.c_void_p, w.DWORD)
wts = c.WinDLL("wtsapi32")
register_session = bind(wts, "WTSRegisterSessionNotification", w.BOOL, H, w.DWORD)
unregister_session = bind(wts, "WTSUnRegisterSessionNotification", w.BOOL, H)


def screens() -> list[QRect]:
    found = []

    @monitor_callback
    def append(_monitor, _dc, region, _data):
        rect = region.contents
        found.append(QRect(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top))
        return True

    win32.checked(enum_monitors(None, None, append, 0))
    return found


def fullscreen(point, monitors) -> bool:
    target = window_at_point(w.POINT(*point))
    window = (root_window(target, 2) or target) if target else foreground()
    if not window:
        return False
    kind = c.create_unicode_buffer(64)
    window_class(window, kind, len(kind))
    if kind.value in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
        return False
    if is_maximized(window) and window_style(window, -16) & 0x00C00000 == 0x00C00000:
        return False
    rectangle = w.RECT()
    if dwm_bounds(window, 9, c.byref(rectangle), c.sizeof(rectangle)) != 0:
        if not window_rect(window, c.byref(rectangle)):
            return False
    result = QRect(rectangle.left, rectangle.top, rectangle.right - rectangle.left, rectangle.bottom - rectangle.top)
    return any(monitor.contains(*point) and result.contains(monitor) for monitor in monitors)


class History:
    def __init__(self, disjoint: bool, interval: float, density: float = 1.0):
        self.parts = deque(maxlen=MAX_PARTS)
        self.anchor = None
        self.interval = max(1.0, interval) / density
        self.density = density
        self.stamp_credit = 0.0
        self.disjoint = disjoint
        self.fade = 0.15 if disjoint else 0.5

    def move(self, point, now):
        if self.anchor is None:
            self.stamp_credit = 0.0
            self.anchor = (*point, now)
            if self.disjoint:
                self.parts.append(self.anchor)
            return
        x, y, _ = self.anchor
        dx, dy = point[0] - x, point[1] - y
        distance = math.hypot(dx, dy)
        if not distance:
            return
        if distance > 512:
            self.parts.clear()
            self.anchor = None
            self.move(point, now)
        elif self.disjoint:
            # Carry fractional stamps between frames so intermediate densities work too.
            self.stamp_credit += self.density
            count = int(self.stamp_credit)
            self.stamp_credit -= count
            self.anchor = (*point, now)
            for step in range(1, count + 1):
                ratio = step / count
                self.parts.append((x + dx * ratio, y + dy * ratio, now))
        else:
            steps = int(distance / self.interval)
            for step in range(max(1, steps - MAX_PARTS), steps):
                ratio = step * self.interval / distance
                self.anchor = (x + dx * ratio, y + dy * ratio, now)
                self.parts.append(self.anchor)

    def expire(self, now):
        while self.parts and now - self.parts[0][2] >= self.fade:
            self.parts.popleft()


class Layer:
    def __init__(self):
        # Layered, click-through, topmost, no activation, absent from Alt+Tab.
        styles = 0x80000 | 0x20 | 0x8 | 0x08000000 | 0x80
        self.handle = win32.checked(create_window(styles, "STATIC", "", 0x80000000,
                                                   0, 0, 0, 0, None, None, None, None))
        self.visible = False

    def hide(self):
        if self.visible:
            show_window(self.handle, 0)
            self.visible = False

    def draw(self, bounds, parts, texture, now, fade, disjoint):
        width, height = bounds.width(), bounds.height()
        with win32.surface(width, height) as (dc, _bitmap, address):
            storage = (c.c_ubyte * (width * height * 4)).from_address(address.value)
            image = QImage(memoryview(storage).cast("B"), width, height, width * 4,
                           QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            painter = QPainter(image)
            if not disjoint:
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            for rect, born in parts:
                painter.setOpacity(max(0.0, 1 - (now - born) / fade))
                painter.drawImage(rect.topLeft() - bounds.topLeft(), texture)
            painter.end()
            # Qt may detach an external buffer when painting.
            c.memmove(address, bytes(image.constBits()), width * height * 4)
            win32.checked(present(self.handle, None, c.byref(w.POINT(bounds.x(), bounds.y())),
                                  c.byref(w.SIZE(width, height)), dc, c.byref(w.POINT()), 0,
                                  c.byref(Blend(0, 0, 255, 1)), 2))
        if not self.visible:
            show_window(self.handle, 4)  # SW_SHOWNOACTIVATE
            self.visible = True
        # A click can raise another topmost window above an already visible layer.
        if get_window(self.handle, 3):  # GW_HWNDPREV
            set_window_pos(self.handle, -1, 0, 0, 0, 0, 0x213)  # TOPMOST, no owner reorder, activation, move or size


class Trail(QAbstractNativeEventFilter):
    def __init__(self, application, window, on_error, on_settings):
        super().__init__()
        self.application, self.window = application, window
        self.on_error, self.on_settings = on_error, on_settings
        self.registered = False
        self.session_registered = bool(register_session(window, 0))
        self.locked = False
        self.history = None
        self.last_point = None
        self.layers = {}
        self.monitors = screens()
        self.timer = QTimer()
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(17)
        self.timer.timeout.connect(self._tick)
        application.installNativeEventFilter(self)

    def configure(self, skin, state, size, density):
        self.stop()
        if skin is None or skin.trail is None:
            return
        scale = state["scale"]
        width, height = (max(1, round(side * scale)) for side in skin.trail.display_size)
        if max(width, height) > 512:
            # shortcut: cap the texture on Windows, increase after measuring oversized trails.
            ratio = 512 / max(width, height)
            width, height = max(1, round(width * ratio)), max(1, round(height * ratio))
        sprite = skin.trail.image.convert("RGBa").resize((width, height))
        pixels = sprite.convert("RGBA").tobytes("raw", "RGBA")
        self.texture = QImage(pixels, width, height, width * 4, QImage.Format.Format_RGBA8888).copy()
        self.texture = self.texture.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        self.centred = skin.cursor_centre or not skin.disjoint_trail
        self.ownership = state["fingerprint"]
        self.cached_cursor = None
        self.last_check = 0
        self.last_point = None
        self.history = History(skin.disjoint_trail, width / render.TRAIL_INTERVAL_DIVISOR / max(1, size), density)
        device = RawDevice(1, 2, 0x100, self.window)  # RIDEV_INPUTSINK
        win32.checked(register_raw(c.byref(device), 1, c.sizeof(device)))
        self.registered = True

    def stop(self):
        self._idle()
        self.history = None
        if self.registered:
            device = RawDevice(1, 2, 1, None)  # RIDEV_REMOVE
            register_raw(c.byref(device), 1, c.sizeof(device))
            self.registered = False

    def close(self):
        self.stop()
        for layer in self.layers.values():
            destroy_window(layer.handle)
        self.layers.clear()
        self.application.removeNativeEventFilter(self)
        if self.session_registered:
            unregister_session(self.window)

    def nativeEventFilter(self, event_type, address):
        if bytes(event_type) in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            message = w.MSG.from_address(int(address))
            if message.message == 0xFF and self.history and not self.locked and not self.timer.isActive():
                info = win32.CursorInfo(c.sizeof(win32.CursorInfo))
                if (win32.get_cursor(c.byref(info)) and info.flags == 1
                        and (info.point.x, info.point.y) != self.last_point):
                    self.timer.start()
            elif message.message == 0x2B1 and message.wParam in (7, 8):  # WTS lock and unlock
                self.locked = message.wParam == 7
                if self.locked:
                    self._idle()
            elif message.message in (0x7E, 0x1A):  # display or system setting change
                QTimer.singleShot(0, self._settings_changed)
        return False, 0

    def _settings_changed(self):
        try:
            monitors = screens()
            if monitors != self.monitors:
                self._idle()
                for layer in self.layers.values():
                    destroy_window(layer.handle)
                self.layers.clear()
                self.monitors = monitors
            self.on_settings()
        except OSError as error:
            self.stop()
            self.on_error(error)

    def _idle(self):
        self.timer.stop()
        if self.history:
            self.history.parts.clear()
            self.history.anchor = None
        for layer in self.layers.values():
            layer.hide()

    def _tick(self):
        try:
            self._draw()
        except (OSError, RuntimeError) as error:
            self.stop()
            self.on_error(error)

    def _draw(self):
        info = win32.CursorInfo(c.sizeof(win32.CursorInfo))
        if not win32.get_cursor(c.byref(info)) or info.flags != 1 or self.locked:
            self._idle()
            return
        point = info.point.x, info.point.y
        self.last_point = point
        now = time.monotonic()
        if now - self.last_check >= 0.5 or info.cursor != self.cached_cursor:
            try:
                self.matches = win32.fingerprint(info.cursor) == self.ownership
            except OSError:
                # The cursor can be replaced between sampling its handle and reading its image.
                self.cached_cursor = None
                self._idle()
                return
            self.cached_cursor, self.last_check = info.cursor, now
        if not self.matches or fullscreen(point, self.monitors):
            self._idle()
            return
        self.history.move(point, now)
        self.history.expire(now)
        if not self.history.parts and self.history.anchor and now - self.history.anchor[2] >= self.history.fade:
            self._idle()
            return

        width, height = self.texture.width(), self.texture.height()
        offset_x, offset_y = (width / 2, height / 2) if self.centred else (0, 0)
        stamps = [(QRect(round(x - offset_x), round(y - offset_y), width, height), born)
                  for x, y, born in self.history.parts]
        visible = set()
        for monitor in self.monitors:
            selected = [(rect, born) for rect, born in stamps if monitor.intersects(rect)]
            if not selected:
                continue
            bounds = QRect()
            for rect, _born in selected:
                bounds = bounds.united(rect.intersected(monitor))
            # shortcut: clip very long diagonal trails to a 1024px box, revisit with GPU rendering.
            if bounds.width() * bounds.height() > 1024 * 1024:
                x, y = selected[-1][0].center().toTuple()
                bounds = QRect(x - 512, y - 512, 1024, 1024).intersected(monitor)
            key = monitor.getRect()
            if key not in self.layers:
                self.layers[key] = Layer()
            self.layers[key].draw(bounds, selected, self.texture, now, self.history.fade, self.history.disjoint)
            visible.add(key)
        for key in self.layers.keys() - visible:
            self.layers[key].hide()
