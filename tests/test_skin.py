import io
import json
import struct
import zipfile

import pytest
from PIL import Image

from osu_cursor import gnome, render, xcursor
from osu_cursor.skin import SkinError, load_skin, parse_general


def png(width=8, height=8, colour=(255, 0, 0, 255)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (width, height), colour).save(buffer, "PNG")
    return buffer.getvalue()


def osk(tmp_path, files: dict[str, bytes], name="skin.osk"):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        for filename, data in files.items():
            archive.writestr(filename, data)
    return path


def test_prefers_2x_and_ignores_case(tmp_path):
    skin = load_skin(osk(tmp_path, {"Cursor.PNG": png(8), "CURSOR@2x.png": png(16, 16)}))
    assert skin.cursor.scale_adjust == 2
    assert skin.cursor.display_size == (8, 8)


def test_reads_flags_and_name(tmp_path):
    ini = b"\xef\xbb\xbf[General]\r\nName: Cool // note\r\nCursorRotate: 0\r\nCursorCentre:0\r\n"
    skin = load_skin(osk(tmp_path, {"cursor.png": png(), "skin.ini": ini}))
    assert skin.name == "Cool"
    assert not skin.cursor_rotate
    assert not skin.cursor_centre
    assert skin.cursor_trail_rotate


def test_flags_outside_general_are_ignored():
    assert parse_general(b"[Colours]\nCursorRotate: 0\n") == {}


def test_disjoint_depends_on_cursormiddle(tmp_path):
    plain = load_skin(osk(tmp_path, {"cursor.png": png(), "cursortrail.png": png()}, "a.osk"))
    full = load_skin(
        osk(tmp_path, {"cursor.png": png(), "cursormiddle.png": png(), "cursortrail.png": png()}, "b.osk")
    )
    assert plain.disjoint_trail
    assert not full.disjoint_trail


def test_transparent_trail_counts_as_no_trail(tmp_path):
    blank = png(1, 1, (0, 0, 0, 0))
    assert load_skin(osk(tmp_path, {"cursor.png": png(), "cursortrail.png": blank})).trail is None


def test_finds_skin_inside_a_parent_folder(tmp_path):
    skin = load_skin(osk(tmp_path, {"My Skin/cursor.png": png()}))
    assert skin.cursor.image.size == (8, 8)


def test_paths_cannot_escape(tmp_path):
    skin = load_skin(osk(tmp_path, {"../../cursor.png": png()}))
    assert skin.cursor is not None
    assert not (tmp_path.parent.parent / "cursor.png").exists()


def test_missing_cursor_is_an_error(tmp_path):
    with pytest.raises(SkinError):
        load_skin(osk(tmp_path, {"skin.ini": b""}))


def test_not_a_zip_is_an_error(tmp_path):
    path = tmp_path / "x.osk"
    path.write_bytes(b"nope")
    with pytest.raises(SkinError):
        load_skin(path)


def write_game_ini(tmp_path, monkeypatch, text):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    (tmp_path / "osu").mkdir()
    (tmp_path / "osu" / "game.ini").write_text(text)


def test_screen_scaling_shrinks_the_gameplay_area(tmp_path, monkeypatch):
    write_game_ini(
        tmp_path, monkeypatch, "Scaling = Gameplay\nScalingSizeX = 0.67\nScalingSizeY = 0.8\n"
    )
    width, height = gnome.gameplay_area(2560, 1600)
    assert (width, height) == pytest.approx((1715.2, 1280))
    assert render.gameplay_scale(width, height, 1) == pytest.approx(1280 / 768)


def test_screen_scaling_off_uses_the_whole_screen(tmp_path, monkeypatch):
    write_game_ini(tmp_path, monkeypatch, "Scaling = Off\nScalingSizeX = 0.5\nScalingSizeY = 0.5\n")
    assert gnome.gameplay_area(2560, 1600) == (2560, 1600)


def test_gameplay_scale_matches_stable_ratio():
    assert render.gameplay_scale(1024, 768, 1) == 1
    assert render.gameplay_scale(2560, 1600, 1) == pytest.approx(1600 / 768)
    # Narrower than 4:3 is limited by width.
    assert render.gameplay_scale(768, 1024, 1) == pytest.approx(576 / 768)


def test_spinning_cursor_has_a_full_revolution(tmp_path):
    skin = load_skin(osk(tmp_path, {"cursor.png": png(32, 32)}))
    frames = render.build_frames(skin, 1.0)
    assert len(frames) == render.SPIN_FRAMES
    assert sum(frame.delay_ms for frame in frames) == pytest.approx(render.REVOLUTION_MS, abs=60)
    assert (frames[0].hot_x * 2, frames[0].hot_y * 2) == frames[0].image.size


def test_still_cursor_with_top_left_origin(tmp_path):
    ini = b"[General]\nCursorRotate: 0\nCursorCentre: 0\n"
    skin = load_skin(osk(tmp_path, {"cursor.png": png(16, 16), "skin.ini": ini}))
    frames = render.build_frames(skin, 1.0)
    assert len(frames) == 1
    frame = frames[0]
    # The texture's corner sits on the hotspot, not its middle.
    assert frame.image.convert("RGBA").getpixel((frame.hot_x + 2, frame.hot_y + 2))[3] == 255
    assert frame.image.convert("RGBA").getpixel((frame.hot_x - 2, frame.hot_y - 2))[3] == 0


def test_xcursor_layout():
    image = Image.new("RGBa", (2, 1), (10, 20, 30, 255))
    data = xcursor.encode([xcursor.Frame(image, 1, 0, 50)], 24)

    assert data[:4] == b"Xcur"
    header_size, version, count = struct.unpack("<III", data[4:16])
    assert (header_size, version, count) == (16, 0x10000, 1)

    kind, nominal, position = struct.unpack("<III", data[16:28])
    assert (kind, nominal) == (0xFFFD0002, 24)
    fields = struct.unpack("<9I", data[position : position + 36])
    assert fields == (36, 0xFFFD0002, 24, 1, 2, 1, 1, 0, 50)
    assert data[position + 36 : position + 40] == bytes([30, 20, 10, 255])
    assert len(data) == position + 36 + 8


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    settings = {"cursor-theme": "'Adwaita'", "cursor-size": "24"}
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(gnome, "screen_size", lambda: (1024, 768))
    monkeypatch.setattr(gnome, "enable_extension", lambda: None)
    monkeypatch.setattr(gnome, "extension_active", lambda: True)
    monkeypatch.setattr(gnome, "_interface_get", settings.__getitem__)
    monkeypatch.setattr(gnome, "_interface_set", settings.__setitem__)
    (tmp_path / "data" / "icons").mkdir(parents=True)
    return settings


def test_size_change_redraws_the_applied_skin(tmp_path, desktop):
    ini = b"[General]\nCursorRotate: 0\n"
    gnome.apply_skin(osk(tmp_path, {"cursor.png": png(40, 40), "skin.ini": ini}), 1.0)
    first_theme = desktop["cursor-theme"]

    result = gnome.set_cursor_size(0.5)

    assert result.size_px == 20
    assert result.skin_name == "skin"
    assert desktop["cursor-theme"] != first_theme
    assert gnome.cursor_size() == 0.5
    assert not (gnome.icons_dir() / first_theme).exists()


def test_new_skin_keeps_the_chosen_size(tmp_path, desktop):
    gnome.apply_skin(osk(tmp_path, {"cursor.png": png(40, 40)}, "a.osk"), 1.5)
    assert gnome.apply_skin(osk(tmp_path, {"cursor.png": png(40, 40)}, "b.osk")).size_px == 60


def test_size_outside_the_game_range_is_refused(desktop):
    with pytest.raises(SkinError):
        gnome.set_cursor_size(2.5)


def test_explains_a_missing_trail(tmp_path, desktop):
    blank = png(1, 1, (0, 0, 0, 0))
    gnome.apply_skin(osk(tmp_path, {"cursor.png": png(), "cursortrail.png": blank}), 1.0)
    assert "trail'i yok" in gnome.trail_problem()


def exports(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    directory = tmp_path / "osu" / "exports"
    directory.mkdir(parents=True)
    return directory


def test_exported_skins_skip_repeats_and_broken_files(tmp_path, monkeypatch):
    directory = exports(tmp_path, monkeypatch)
    trail = {"cursor.png": png(), "cursortrail.png": png(), "skin.ini": b"[General]\nName: B   skin\n"}
    osk(directory, trail, "b.osk")
    osk(directory, trail, "b (1).osk")
    osk(directory, {"cursor.png": png(colour=(0, 255, 0, 255))}, "a.osk")
    (directory / "broken.osk").write_bytes(b"not a zip")

    skins = gnome.exported_skins()

    assert [skin.name for skin in skins] == ["a", "B skin"]
    assert [skin.has_trail for skin in skins] == [False, True]
    assert Image.open(io.BytesIO(skins[0].preview_png)).size == (96, 96)


def test_current_skin_key_matches_the_exported_skin(tmp_path, monkeypatch):
    directory = exports(tmp_path, monkeypatch)
    files = {"cursor.png": png()}
    osk(directory, files, "a.osk")
    gnome._keep_source(files, "kept")
    assert gnome.current_skin_key() == gnome.exported_skins()[0].key


def test_game_cursor_size_is_kept_in_range(tmp_path, monkeypatch):
    write_game_ini(tmp_path, monkeypatch, "GameplayCursorSize = 9\n")
    assert gnome.has_game_cursor_size()
    assert gnome.game_cursor_size() == gnome.MAX_CURSOR_SIZE


def test_settings_keep_each_other(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    gnome._save_cursor_size(1.5)
    gnome.set_trail_enabled(False)
    gnome._save_cursor_size(0.5)
    assert gnome.cursor_size() == 0.5
    assert not gnome.trail_enabled()


def test_turning_the_trail_off_updates_the_running_state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    state = gnome.data_dir() / "state.json"
    state.parent.mkdir(parents=True)
    state.write_text('{"skin": "s", "trail": {"file": "x"}}')
    gnome.set_trail_enabled(False)
    assert json.loads(state.read_text()) == {
        "skin": "s", "trail": {"file": "x"}, "trail_enabled": False,
    }


@pytest.mark.parametrize(
    ("info", "expected"),
    [
        ({"state": 1.0}, None),
        ({"state": 4.0}, "uyumlu değil"),
        ({"state": 3.0, "error": "patladı"}, "patladı"),
        ({"state": 2.0}, "Eklentiler"),
        ({}, "oturumu kapatıp"),
    ],
)
def test_trail_problem_names_the_extension_state(tmp_path, monkeypatch, info, expected):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    state = gnome.data_dir() / "state.json"
    state.parent.mkdir(parents=True)
    state.write_text('{"skin": "s", "trail": {"file": "x"}}')
    monkeypatch.setattr(gnome, "_extension_info", lambda: info)
    problem = gnome.trail_problem()
    assert problem is None if expected is None else expected in problem


def test_no_warning_when_the_trail_is_turned_off(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    state = gnome.data_dir() / "state.json"
    state.parent.mkdir(parents=True)
    state.write_text('{"skin": "s", "trail": null}')
    gnome.set_trail_enabled(False)
    assert gnome.trail_problem() is None
