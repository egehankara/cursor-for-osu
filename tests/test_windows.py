import io
import ctypes
import sys
import zipfile
from ctypes import wintypes

import pytest

if sys.platform != "win32":
    pytest.skip("Windows integration tests", allow_module_level=True)

from PIL import Image
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QWidget

from osu_cursor import library, win32, windows, windows_gui, windows_trail
from osu_cursor.skin import SkinError
from osu_cursor.windows_trail import History
from osu_cursor.xcursor import Frame


def png(color="cyan"):
    buffer = io.BytesIO()
    Image.new("RGBA", (24, 24), color).save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "user"))
    monkeypatch.setattr(win32, "get_metrics", lambda axis: (1920, 1080)[axis])
    state = {"system": "original", "roles": (), "resets": 0}

    def replace(frame, roles, clear_old):
        if clear_old:
            reset()
        state.update(system=str(frame.image.size), roles=roles)
        return state["system"]

    def reset():
        state.update(system="original", roles=(), resets=state["resets"] + 1)

    monkeypatch.setattr(win32, "stock_cursor", lambda _role: object())
    monkeypatch.setattr(win32, "fingerprint", lambda _cursor: state["system"])
    monkeypatch.setattr(win32, "replace", replace)
    monkeypatch.setattr(win32, "reset", reset)
    skin = tmp_path / "Pointer.osk"
    with zipfile.ZipFile(skin, "w") as archive:
        archive.writestr("skin/cursor.png", png())
        archive.writestr("skin/cursortrail.png", png("magenta"))
        archive.writestr("skin/extra.txt", "should not be copied")
    return skin, state


def test_import_apply_change_size_rename_and_remove(desktop):
    source, system = desktop
    library.add_skin(source)
    skin, = library.library_skins()
    assert source.is_file()
    assert sorted(p.name for p in skin.path.iterdir()) == ["cursor.png", "cursortrail.png"]
    with pytest.raises(SkinError, match="already in the list"):
        library.add_skin(source)

    assert windows.apply_skin(skin.path).has_trail
    assert system["roles"] == (win32.ARROW,)
    assert windows.active()["key"] == skin.key
    original_size = system["system"]
    windows.set_cursor_size(1.5)
    assert system["system"] != original_size
    windows.rename_skin(skin.path, "New")
    assert windows.active()["name"] == library.library_skins()[0].name == "New"
    windows.set_keep_system_cursors(False)
    assert system["roles"] == win32.SHAPES
    windows.set_keep_system_cursors(True)
    assert system["roles"] == (win32.ARROW,)
    windows.remove_skin(skin.path)
    assert system["system"] == "original"
    assert not windows.active() and not library.library_skins()
    assert source.is_file()


def test_windows_scheme_change_invalidates_saved_skin(desktop):
    source, system = desktop
    windows.apply_skin(source)
    system["system"] = "chosen in Settings"
    assert windows.active() == {}
    assert windows.set_cursor_size(1.7) is None
    assert system["system"] == "chosen in Settings"


def test_failed_cursor_change_rolls_back(desktop, monkeypatch):
    source, system = desktop
    windows.apply_skin(source)

    def fail(*_args):
        system["system"] = "partial"
        raise OSError("failed cursor change")

    monkeypatch.setattr(win32, "replace", fail)
    with pytest.raises(OSError, match="failed cursor change"):
        windows.set_cursor_size(1.25)
    assert system["system"] == "original"
    assert not windows.active()
    assert windows.cursor_size() == 1


def test_folder_import_and_invalid_archive(desktop):
    source, _system = desktop
    folder = source.parent / "Folder skin"
    folder.mkdir()
    (folder / "cursor.png").write_bytes(png("yellow"))
    library.add_skin(folder)
    assert library.library_skins()[0].name == "Folder skin"
    source.write_text("invalid archive")
    with pytest.raises(SkinError, match="not a valid .osk"):
        library.add_skin(source)
    (folder / "cursor.png").write_bytes(b"broken image")
    with pytest.raises(SkinError):
        library.add_skin(folder)


@pytest.mark.parametrize("disjoint,expiry", [(True, 0.15), (False, 0.5)])
def test_trail_expires(disjoint, expiry):
    history = History(disjoint, 4)
    history.move((10, 10), 0)
    history.move((40, 10), 0.05)
    assert history.parts
    assert history.parts[-1][0] == (40 if disjoint else 34)
    history.expire(0.05 + expiry + 0.001)
    assert not history.parts


def test_win32_cursor_bitmap_round_trip():
    image = Image.new("RGBA", (31, 29), (90, 180, 255, 155)).convert("RGBa")
    first = win32.create_cursor(Frame(image, 3, 7))
    second = win32.create_cursor(Frame(image, 4, 7))
    try:
        assert win32.fingerprint(first)
        assert win32.fingerprint(first) != win32.fingerprint(second)
    finally:
        win32.destroy_cursor(first)
        win32.destroy_cursor(second)


@pytest.fixture
def trail_input(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    monkeypatch.setattr(windows_trail, "register_session", lambda *_: False)
    errors = []
    trail = windows_trail.Trail(app, int(window.winId()), errors.append, lambda: None)
    trail.history = History(False, 4)
    trail.last_point = (40, 80)
    point = wintypes.POINT(*trail.last_point)

    def get_cursor(pointer):
        info = ctypes.cast(pointer, ctypes.POINTER(win32.CursorInfo)).contents
        info.flags, info.point = 1, point
        return True

    monkeypatch.setattr(win32, "get_cursor", get_cursor)
    event = wintypes.MSG()
    event.message = 0xFF

    def mouse_input():
        trail.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(event))

    try:
        yield trail, point, mouse_input, errors
    finally:
        trail.close()


def test_stationary_mouse_message_leaves_trail_idle(trail_input):
    trail, point, mouse_input, _ = trail_input
    mouse_input()
    assert not trail.timer.isActive()
    point.x += 10
    mouse_input()
    assert trail.timer.isActive()


def test_trail_recovers_when_cursor_handle_changes_during_click(trail_input, monkeypatch):
    trail, point, mouse_input, errors = trail_input
    history = trail.history
    trail.cached_cursor = None
    trail.last_check = 0

    def stale_cursor(_):
        raise OSError("Invalid cursor handle")

    monkeypatch.setattr(win32, "fingerprint", stale_cursor)
    point.x += 10
    mouse_input()
    trail._tick()
    assert not trail.timer.isActive()
    assert trail.history is history and not errors

    point.x += 10
    mouse_input()
    assert trail.timer.isActive()


def test_window_close_keeps_trail_until_tray_quit(desktop, monkeypatch):
    source, _ = desktop
    windows.apply_skin(source)
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    window = windows_gui.Window(app)
    window.show()
    try:
        assert window.trail.registered
        window.close()
        assert not window.isVisible() and window.tray_icon.isVisible()
        assert window.trail.registered

        open_action, quit_action = window.tray_icon.contextMenu().actions()
        open_action.trigger()
        assert window.isVisible() and window.trail.registered

        window.close()
        QTimer.singleShot(0, quit_action.trigger)
        assert app.exec() == 0
        assert not window.trail.registered and not window.tray_icon.isVisible()
        assert windows.active()
    finally:
        window._shutdown()
        window.close()
