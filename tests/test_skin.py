import io
import json
import struct
import zipfile
from pathlib import Path

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
    assert not skin.cursor_centre


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


def test_a_skin_without_a_trail_is_not_reported_as_a_problem(tmp_path, desktop):
    blank = png(1, 1, (0, 0, 0, 0))
    gnome.apply_skin(osk(tmp_path, {"cursor.png": png(), "cursortrail.png": blank}), 1.0)
    assert gnome.trail_problem() is None


def library(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    source = tmp_path / "downloads"
    source.mkdir()
    return source


def test_library_lists_added_skins_by_name(tmp_path, monkeypatch):
    source = library(tmp_path, monkeypatch)
    trail = {"cursor.png": png(), "cursortrail.png": png(), "skin.ini": b"[General]\nName: B   skin\n"}
    gnome.add_skin(osk(source, trail, "b.osk"))
    gnome.add_skin(osk(source, {"cursor.png": png(colour=(0, 255, 0, 255))}, "a.osk"))
    (gnome.skins_dir() / "broken.osk").write_bytes(b"not a zip")

    skins = gnome.library_skins()

    assert [skin.name for skin in skins] == ["a", "B skin"]
    assert [skin.has_trail for skin in skins] == [False, True]
    assert Image.open(io.BytesIO(skins[0].preview_png)).size == (96, 48)


def test_an_oversized_cursor_says_so(tmp_path):
    with pytest.raises(SkinError, match="çok büyük .4097×1"):
        load_skin(osk(tmp_path, {"cursor.png": png(4097, 1)}))


def test_a_missing_cursor_still_says_it_is_missing(tmp_path):
    with pytest.raises(SkinError, match="cursor.png yok"):
        load_skin(osk(tmp_path, {"hitcircle.png": png()}))


def test_an_oversized_2x_falls_back_to_the_normal_cursor(tmp_path):
    skin = load_skin(osk(tmp_path, {"cursor@2x.png": png(4097, 1), "cursor.png": png(8, 8)}))
    assert skin.cursor.scale_adjust == 1


def spinning(tmp_path, side):
    return load_skin(osk(tmp_path, {"cursor.png": png(side, side)}))


def visible_area(image):
    return sum(1 for value in image.convert("RGBA").getchannel("A").tobytes() if value)


def canvas_for(tmp_path, image, ini=b"[General]\nCursorRotate: 0\nCursorCentre: 1\n", scale=1.0):
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return render.build_frames(load_skin(osk(tmp_path, {"cursor.png": buffer.getvalue(), "skin.ini": ini})), scale)[0]


def test_the_canvas_stops_at_the_visible_part(tmp_path):
    image = Image.new("RGBA", (100, 100))
    image.paste((255, 0, 0, 255), (45, 45, 55, 55))
    frame = canvas_for(tmp_path, image)
    assert frame.image.width < 40
    assert (frame.hot_x, frame.hot_y) == (frame.image.width // 2, frame.image.height // 2)
    assert visible_area(frame.image) == 100


@pytest.mark.parametrize("centre", [b"1", b"0"])
def test_nothing_visible_is_cut_off_at_the_corners(tmp_path, centre):
    image = Image.new("RGBA", (64, 64))
    for corner in ((0, 0), (63, 0), (0, 63), (63, 63)):
        image.putpixel(corner, (255, 0, 0, 255))
    frame = canvas_for(tmp_path, image, b"[General]\nCursorRotate: 0\nCursorCentre: " + centre + b"\n")
    assert visible_area(frame.image) == 4


def test_a_fully_transparent_cursor_still_gets_a_canvas(tmp_path):
    frame = canvas_for(tmp_path, Image.new("RGBA", (16, 16)))
    assert frame.image.size == (1, 1)


def test_every_skin_is_still_even_when_it_asks_to_spin(tmp_path):
    ini = b"[General]\nCursorRotate: 1\nCursorTrailRotate: 1\n"
    frames = render.build_frames(load_skin(osk(tmp_path, {"cursor.png": png(16, 16), "skin.ini": ini})), 1.0)
    assert [frame.delay_ms for frame in frames] == [0]


def test_a_skin_that_does_not_say_stays_still_too(tmp_path):
    assert len(render.build_frames(spinning(tmp_path, 16), 1.0)) == 1


def test_a_top_left_cursor_keeps_its_hotspot(tmp_path):
    image = Image.new("RGBA", (40, 40))
    image.paste((255, 0, 0, 255), (10, 10, 20, 20))
    frame = canvas_for(tmp_path, image, b"[General]\nCursorCentre: 0\n")
    assert (frame.hot_x, frame.hot_y) == (0, 0)
    assert frame.image.size == (20, 20)


def test_the_hotspot_stays_inside_a_ring_shaped_corner_cursor(tmp_path):
    image = Image.new("RGBA", (100, 100))
    image.paste((255, 0, 0, 255), (70, 70, 80, 80))
    frame = canvas_for(tmp_path, image)
    assert 0 <= frame.hot_x < frame.image.width and 0 <= frame.hot_y < frame.image.height
    assert (frame.hot_x, frame.hot_y) == (0, 0)
    assert frame.image.size == (30, 30)


def test_a_larger_cursormiddle_is_not_cut_off(tmp_path):
    cursor = png(8, 8)
    middle = png(32, 32, (0, 255, 0, 255))
    skin = load_skin(osk(tmp_path, {"cursor.png": cursor, "cursormiddle.png": middle}))
    frame = render.build_frames(skin, 1.0)[0]
    assert frame.image.size == (32, 32)
    assert (frame.hot_x, frame.hot_y) == (16, 16)


def test_the_trail_state_says_nothing_about_spinning(tmp_path, desktop):
    ini = b"[General]\nCursorRotate: 1\nCursorTrailRotate: 1\n"
    gnome.apply_skin(osk(tmp_path, {"cursor.png": png(), "cursortrail.png": png(), "skin.ini": ini}), 1.0)
    state = json.loads((gnome.data_dir() / "state.json").read_text())
    assert "rotate" not in state["trail"]


def test_a_huge_cursor_is_refused_before_it_is_resized(tmp_path, monkeypatch):
    skin = spinning(tmp_path, 16)
    monkeypatch.setattr(render, "MAX_CURSOR_BYTES", 16)
    monkeypatch.setattr(render, "_scaled", lambda *_args: pytest.fail("resized anyway"))
    with pytest.raises(SkinError, match="çok büyük"):
        render.build_frames(skin, 1.0)


def test_a_refused_cursor_leaves_the_applied_skin_alone(tmp_path, desktop, monkeypatch):
    gnome.apply_skin(osk(tmp_path, {"cursor.png": png(16, 16)}, "a.osk"), 1.0)
    theme = desktop["cursor-theme"]
    monkeypatch.setattr(render, "MAX_CURSOR_BYTES", 16)

    with pytest.raises(SkinError, match="çok büyük"):
        gnome.apply_skin(osk(tmp_path, {"cursor.png": png(32, 32)}, "b.osk"), 1.0)

    assert desktop["cursor-theme"] == theme
    assert gnome.current_skin() == "a"
    assert [entry.name for entry in gnome.icons_dir().iterdir()] == [theme]


def test_library_is_empty_before_anything_is_added(tmp_path, monkeypatch):
    library(tmp_path, monkeypatch)
    assert gnome.library_skins() == []


def test_add_keeps_only_cursor_files_and_leaves_the_original(tmp_path, monkeypatch):
    source = library(tmp_path, monkeypatch)
    original = osk(
        source,
        {"cursor.png": png(), "cursortrail-0.png": png(), "hitcircle.png": png(), "skin.ini": b""},
        "a.osk",
    )
    before = original.read_bytes()

    gnome.add_skin(original)

    assert original.read_bytes() == before
    assert sorted(file.name for file in (gnome.skins_dir() / "a").iterdir()) == ["cursor.png", "skin.ini"]


def test_add_refuses_the_same_skin_twice(tmp_path, monkeypatch):
    source = library(tmp_path, monkeypatch)
    files = {"cursor.png": png()}
    gnome.add_skin(osk(source, files, "a.osk"))
    with pytest.raises(SkinError, match="zaten listede"):
        gnome.add_skin(osk(source, files, "b.osk"))


def test_add_refuses_a_skin_with_no_cursor(tmp_path, monkeypatch):
    source = library(tmp_path, monkeypatch)
    with pytest.raises(SkinError):
        gnome.add_skin(osk(source, {"hitcircle.png": png()}, "a.osk"))
    assert gnome.library_skins() == []


def test_different_skins_with_one_file_name_are_both_kept(tmp_path, monkeypatch):
    source = library(tmp_path, monkeypatch)
    gnome.add_skin(osk(source, {"cursor.png": png()}, "a.osk"))
    gnome.add_skin(osk(source, {"cursor.png": png(colour=(0, 255, 0, 255))}, "a.osk"))
    assert sorted(path.name for path in gnome.skins_dir().iterdir()) == ["a", "a (2)"]


def test_remove_deletes_only_the_library_copy(tmp_path, monkeypatch):
    source = library(tmp_path, monkeypatch)
    original = osk(source, {"cursor.png": png()}, "a.osk")
    gnome.add_skin(original)

    gnome.remove_skin(gnome.library_skins()[0].path)

    assert gnome.library_skins() == []
    assert original.exists()


def test_remove_refuses_files_outside_the_library(tmp_path, monkeypatch):
    source = library(tmp_path, monkeypatch)
    original = osk(source, {"cursor.png": png()}, "a.osk")
    with pytest.raises(SkinError):
        gnome.remove_skin(original)
    assert original.exists()


def test_exports_are_added_once_as_cursor_files_only(tmp_path, monkeypatch):
    library(tmp_path, monkeypatch)
    exports = gnome.exports_dir()
    exports.mkdir(parents=True)
    original = osk(exports, {"cursor.png": png(), "hitcircle.png": png()}, "a.osk")
    osk(exports, {"cursor.png": png()}, "a (1).osk")
    osk(exports, {"cursor.png": png(colour=(0, 255, 0, 255))}, "b.OSK")
    osk(exports, {"hitcircle.png": png()}, "no-cursor.osk")
    (exports / "broken.osk").write_bytes(b"not a zip")
    (exports / "notes.txt").write_text("skip me")
    before = original.read_bytes()

    assert gnome.add_exported_skins() == 2
    assert gnome.add_exported_skins() == 0

    assert sorted(path.name for path in gnome.skins_dir().iterdir()) == ["a", "b"]
    assert original.read_bytes() == before
    assert [file.name for file in (gnome.skins_dir() / "a").iterdir()] == ["cursor.png"]


def test_add_exports_without_an_exports_folder(tmp_path, monkeypatch):
    library(tmp_path, monkeypatch)
    assert gnome.add_exported_skins() == 0


def test_rename_changes_the_listed_name_only(tmp_path, monkeypatch):
    source = library(tmp_path, monkeypatch)
    files = {"cursor.png": png(), "skin.ini": b"[General]\nName: Old\n"}
    original = osk(source, files, "a.osk")
    gnome.add_skin(original)
    before = gnome.library_skins()[0]

    gnome.rename_skin(before.path, "  Yeni   isim ")

    after = gnome.library_skins()[0]
    assert (after.name, after.path, after.key) == ("Yeni isim", before.path, before.key)
    with zipfile.ZipFile(original) as untouched:
        assert gnome.NAME_ENTRY not in untouched.namelist()
    with pytest.raises(SkinError, match="zaten listede"):
        gnome.add_skin(original)


def test_rename_refuses_empty_names_and_outside_files(tmp_path, monkeypatch):
    source = library(tmp_path, monkeypatch)
    original = osk(source, {"cursor.png": png()}, "a.osk")
    gnome.add_skin(original)
    with pytest.raises(SkinError, match="boş"):
        gnome.rename_skin(gnome.library_skins()[0].path, "   ")
    with pytest.raises(SkinError):
        gnome.rename_skin(original, "x")


def test_a_name_inside_a_downloaded_skin_is_not_used(tmp_path, monkeypatch):
    source = library(tmp_path, monkeypatch)
    gnome.add_skin(osk(source, {"cursor.png": png(), gnome.NAME_ENTRY: b"sneaky"}, "a.osk"))
    assert gnome.library_skins()[0].name == "a"


def test_renaming_the_applied_skin_updates_it_and_survives_a_size_change(tmp_path, desktop):
    source = tmp_path / "downloads"
    source.mkdir()
    gnome.add_skin(osk(source, {"cursor.png": png(40, 40)}, "a.osk"))
    skin = gnome.library_skins()[0]
    gnome.apply_skin(skin.path, 1.0)

    gnome.rename_skin(skin.path, "Yeni")
    assert gnome.current_skin() == "Yeni"
    assert gnome.current_skin_key() == skin.key

    gnome.set_cursor_size(1.5)
    assert gnome.current_skin() == "Yeni"

    gnome.apply_skin(gnome.library_skins()[0].path, 1.0)
    assert gnome.current_skin() == "Yeni"


def skin_folder(parent, name, files):
    folder = parent / name
    folder.mkdir()
    for filename, data in files.items():
        (folder / filename).write_bytes(data)
    return folder


def test_a_folder_can_be_added_and_keeps_the_dots_in_its_name(tmp_path, monkeypatch):
    source = library(tmp_path, monkeypatch)
    folder = skin_folder(
        source, "Skin v1.2", {"Cursor.PNG": png(), "hitcircle.png": png(), gnome.NAME_ENTRY: b"sneaky"}
    )

    gnome.add_skin(folder)

    skin = gnome.library_skins()[0]
    assert (skin.name, skin.path.name) == ("Skin v1.2", "Skin v1.2")
    assert [file.name for file in skin.path.iterdir()] == ["cursor.png"]
    assert sorted(file.name for file in folder.iterdir()) == sorted(
        ["Cursor.PNG", "hitcircle.png", gnome.NAME_ENTRY]
    )


def test_a_folder_and_an_osk_of_one_skin_count_as_the_same(tmp_path, monkeypatch):
    source = library(tmp_path, monkeypatch)
    files = {"cursor.png": png()}
    gnome.add_skin(skin_folder(source, "folder", files))
    with pytest.raises(SkinError, match="zaten listede"):
        gnome.add_skin(osk(source, files, "a.osk"))


def test_a_folder_without_a_cursor_is_refused(tmp_path, monkeypatch):
    source = library(tmp_path, monkeypatch)
    with pytest.raises(SkinError):
        gnome.add_skin(skin_folder(source, "empty", {"hitcircle.png": png()}))
    assert gnome.library_skins() == []


def test_old_archives_become_folders_and_keep_their_names(tmp_path, monkeypatch):
    library(tmp_path, monkeypatch)
    gnome.skins_dir().mkdir(parents=True)
    osk(gnome.skins_dir(), {"cursor.png": png(), gnome.NAME_ENTRY: "Özel".encode()}, "a.osk")
    (gnome.skins_dir() / "broken.osk").write_bytes(b"not a zip")

    skins = gnome.library_skins()

    assert [(skin.name, skin.path.name) for skin in skins] == [("Özel", "a")]
    assert skins[0].path.is_dir()
    assert not (gnome.skins_dir() / "a.osk").exists()
    assert (gnome.skins_dir() / "broken.osk").exists()


def test_remove_deletes_the_whole_folder(tmp_path, monkeypatch):
    source = library(tmp_path, monkeypatch)
    gnome.add_skin(osk(source, {"cursor.png": png()}, "a.osk"))
    folder = gnome.library_skins()[0].path
    gnome.rename_skin(folder, "Yeni")

    gnome.remove_skin(folder)

    assert not folder.exists()
    assert list(gnome.skins_dir().iterdir()) == []


def test_add_skins_goes_on_after_a_bad_one(tmp_path, monkeypatch):
    source = library(tmp_path, monkeypatch)
    first = osk(source, {"cursor.png": png()}, "a.osk")
    second = osk(source, {"cursor.png": png(colour=(0, 255, 0, 255))}, "b.osk")
    broken = source / "broken.osk"
    broken.write_bytes(b"not a zip")

    assert gnome.add_skins([str(first), str(broken), str(first), str(second)]) == (2, 2)
    assert sorted(skin.name for skin in gnome.library_skins()) == ["a", "b"]


def test_a_folder_that_vanishes_during_a_read_is_skipped(tmp_path, monkeypatch):
    source = library(tmp_path, monkeypatch)
    gnome.add_skin(osk(source, {"cursor.png": png()}, "a.osk"))
    gnome.add_skin(osk(source, {"cursor.png": png(colour=(0, 255, 0, 255))}, "b.osk"))
    real = gnome.read_cursor_files

    def flaky(path):
        if Path(path).name == "a":
            raise FileNotFoundError(path)
        return real(path)

    monkeypatch.setattr(gnome, "read_cursor_files", flaky)
    assert [skin.name for skin in gnome.library_skins()] == ["b"]


def test_removing_the_skin_in_use_goes_back_to_the_previous_cursor(tmp_path, desktop):
    source = tmp_path / "downloads"
    source.mkdir()
    gnome.add_skin(osk(source, {"cursor.png": png(16, 16)}, "a.osk"))
    skin = gnome.library_skins()[0]
    gnome.apply_skin(skin.path, 1.0)

    gnome.remove_skin(skin.path)

    assert desktop["cursor-theme"] == "Adwaita"
    assert gnome.current_skin() is None
    assert gnome.library_skins() == []


def test_removing_another_skin_keeps_the_cursor_in_use(tmp_path, desktop):
    source = tmp_path / "downloads"
    source.mkdir()
    gnome.add_skin(osk(source, {"cursor.png": png(16, 16)}, "a.osk"))
    gnome.add_skin(osk(source, {"cursor.png": png(16, 16, (0, 255, 0, 255))}, "b.osk"))
    used, other = gnome.library_skins()
    gnome.apply_skin(used.path, 1.0)
    theme = desktop["cursor-theme"]

    gnome.remove_skin(other.path)

    assert desktop["cursor-theme"] == theme
    assert gnome.current_skin() == "a"


def test_current_skin_key_matches_the_library_skin(tmp_path, monkeypatch):
    source = library(tmp_path, monkeypatch)
    files = {"cursor.png": png()}
    gnome.add_skin(osk(source, files, "a.osk"))
    gnome._keep_source(files, "kept")
    assert gnome.current_skin_key() == gnome.library_skins()[0].key


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


def alpha_at(image, x):
    return image.getpixel((x, image.height // 2))[3]


def preview_of(tmp_path, files):
    return render.preview(load_skin(osk(tmp_path, files)), 192, 96)


def test_preview_shows_a_stamped_trail_fading_behind_the_cursor(tmp_path):
    image = preview_of(tmp_path, {"cursor.png": png(), "cursortrail.png": png(2, 2)})
    assert alpha_at(image, 144) == 255
    assert 0 < alpha_at(image, 40) < alpha_at(image, 90) < 255


def test_preview_builds_up_a_continuous_trail(tmp_path):
    colour = (40, 40, 40, 100)
    files = {
        "cursor.png": png(colour=(0, 0, 0, 0)),
        "cursormiddle.png": png(2, 2),
        "cursortrail.png": png(colour=colour),
    }
    image = preview_of(tmp_path, files)
    # The parts sit 38 pixels apart and are 96 wide, so only x=100 is covered by two.
    assert alpha_at(image, 100) == pytest.approx(alpha_at(image, 120) + alpha_at(image, 40), abs=2)
    assert alpha_at(image, 120) > alpha_at(image, 40) > 0


def test_preview_without_a_trail_leaves_the_left_side_empty(tmp_path):
    image = preview_of(tmp_path, {"cursor.png": png()})
    assert alpha_at(image, 144) == 255
    assert alpha_at(image, 40) == 0


def test_preview_keeps_a_top_left_cursor_on_the_canvas(tmp_path):
    ini = b"[General]\nCursorCentre: 0\n"
    image = preview_of(tmp_path, {"cursor.png": png(), "skin.ini": ini})
    assert alpha_at(image, 144) == 255
