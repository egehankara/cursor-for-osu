"""The window: pick a skin, set the cursor size and turn the trail on or off."""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import gnome  # noqa: E402
from .skin import SkinError  # noqa: E402

APP_ID = "io.github.xrayzack1010.OsuCursor"
SIZE_SETTLE_MS = 300
PREVIEW_DISPLAY_SIZE = 48


class Window(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application):
        super().__init__(application=application, title="osu! Cursor")
        self.set_default_size(560, 780)
        self._busy = False
        self._pending_size: float | None = None
        self._size_timer = 0
        self._skin_checks: list[tuple[str, Gtk.Image]] = []

        self._title = Adw.WindowTitle(title="osu! Cursor")
        self._banner = Adw.Banner(use_markup=False)

        page = Adw.PreferencesPage()
        page.add(self._build_settings())
        page.add(self._build_skins())
        page.add(self._build_reset())

        self._toasts = Adw.ToastOverlay(child=page)
        content = Adw.ToolbarView(content=self._toasts)
        content.add_top_bar(Adw.HeaderBar(title_widget=self._title))
        content.add_top_bar(self._banner)
        self.set_content(content)

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self._on_drop)
        self._toasts.add_controller(drop)

        self._refresh()
        self._load_skins()

    def _build_settings(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Ayarlar")

        self._size_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, gnome.MIN_CURSOR_SIZE, gnome.MAX_CURSOR_SIZE, 0.01
        )
        self._size_scale.set_digits(2)
        self._size_scale.set_draw_value(True)
        self._size_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self._size_scale.set_size_request(260, -1)
        self._size_scale.set_valign(Gtk.Align.CENTER)
        self._size_scale.add_mark(1.0, Gtk.PositionType.BOTTOM, None)
        self._size_scale.set_value(gnome.cursor_size())
        self._size_scale.connect("value-changed", self._on_size_changed)
        size_row = Adw.ActionRow(title="Cursor boyutu")
        size_row.add_suffix(self._size_scale)
        group.add(size_row)

        if gnome.has_game_cursor_size():
            game_size = gnome.game_cursor_size()
            use_button = Gtk.Button(label="Kullan", valign=Gtk.Align.CENTER)
            use_button.connect("clicked", lambda _button: self._size_scale.set_value(game_size))
            game_row = Adw.ActionRow(
                title="Oyundaki boyut", subtitle=f"osu!lazer ayarın: {game_size:.2f}"
            )
            game_row.add_suffix(use_button)
            group.add(game_row)

        self._trail_row = Adw.SwitchRow(
            title="Trail", subtitle="Kapalıyken sadece imleç kalır", active=gnome.trail_enabled()
        )
        self._trail_row.connect("notify::active", self._on_trail_toggled)
        group.add(self._trail_row)
        return group

    def _build_skins(self) -> Adw.PreferencesGroup:
        self._skins = Adw.PreferencesGroup(
            title="Skin'ler", description=".osk dosyasını pencereye de bırakabilirsin."
        )
        open_button = Gtk.Button(label="Dosya seç", valign=Gtk.Align.CENTER)
        open_button.connect("clicked", self._on_open)
        self._skins.set_header_suffix(open_button)
        return self._skins

    def _build_reset(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup()
        self._reset_row = Adw.ButtonRow(title="Önceki imlece dön")
        self._reset_row.connect("activated", self._on_reset)
        group.add(self._reset_row)
        return group

    def _load_skins(self) -> None:
        def work() -> None:
            try:
                skins = gnome.exported_skins()
            except Exception as failure:  # shown to the user instead of a silent thread death
                GLib.idle_add(self._toast, f"Skin'ler okunamadı: {failure}")
                return
            GLib.idle_add(self._show_skins, skins)

        threading.Thread(target=work, daemon=True).start()

    def _show_skins(self, skins: list[gnome.ExportedSkin]) -> bool:
        if not skins:
            self._skins.set_description(
                "osu!lazer'den export edilmiş skin yok. .osk dosyasını pencereye bırakabilirsin."
            )
        for skin in skins:
            row = Adw.ActionRow(
                title=skin.name,
                subtitle="Trail var" if skin.has_trail else "Trail yok",
                use_markup=False,
                activatable=True,
            )
            texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(skin.preview_png))
            row.add_prefix(Gtk.Image(paintable=texture, pixel_size=PREVIEW_DISPLAY_SIZE))
            check = Gtk.Image(icon_name="object-select-symbolic", visible=False)
            row.add_suffix(check)
            row.connect("activated", self._on_skin_activated, skin.path)
            self._skins.add(row)
            self._skin_checks.append((skin.key, check))
        self._refresh()
        return GLib.SOURCE_REMOVE

    def _refresh(self) -> None:
        skin = gnome.current_skin()
        self._title.set_subtitle(" ".join(skin.split()) if skin else "Henüz skin uygulanmadı")

        problem = gnome.trail_problem()
        self._banner.set_title(problem or "")
        self._banner.set_revealed(problem is not None)

        self._reset_row.set_sensitive(skin is not None and not self._busy)
        current = gnome.current_skin_key()
        for key, check in self._skin_checks:
            check.set_visible(key == current)

    def _toast(self, text: str) -> bool:
        self._toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text)))
        return GLib.SOURCE_REMOVE

    def _on_skin_activated(self, _row, path: Path) -> None:
        self._apply(str(path))

    def _on_drop(self, _target, value, _x, _y) -> bool:
        files = value.get_files()
        if not files or files[0].get_path() is None:
            return False
        self._apply(files[0].get_path())
        return True

    def _on_open(self, _button) -> None:
        osk_filter = Gtk.FileFilter(name="osu! skin")
        osk_filter.add_pattern("*.osk")
        osk_filter.add_pattern("*.OSK")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(osk_filter)
        dialog = Gtk.FileDialog(title="Skin seç", filters=filters)
        dialog.open(self, None, self._on_chosen)

    def _on_chosen(self, dialog, result) -> None:
        try:
            chosen = dialog.open_finish(result)
        except GLib.Error:
            return  # the dialog was cancelled
        if chosen.get_path():
            self._apply(chosen.get_path())

    def _on_trail_toggled(self, row, _param) -> None:
        try:
            gnome.set_trail_enabled(row.get_active())
        except OSError as failure:
            self._toast(str(failure))
        self._refresh()

    def _on_size_changed(self, _scale) -> None:
        # Redrawing takes a moment, so wait until the slider stops moving.
        if self._size_timer:
            GLib.source_remove(self._size_timer)
        self._size_timer = GLib.timeout_add(SIZE_SETTLE_MS, self._commit_size)

    def _commit_size(self) -> bool:
        self._size_timer = 0
        self._pending_size = round(self._size_scale.get_value(), 2)
        self._run_pending_size()
        return GLib.SOURCE_REMOVE

    def _run_pending_size(self) -> None:
        if self._busy or self._pending_size is None:
            return
        size, self._pending_size = self._pending_size, None
        self._run(lambda: gnome.set_cursor_size(size), None)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._skins.set_sensitive(not busy)
        self._trail_row.set_sensitive(not busy)
        if busy:
            self._reset_row.set_sensitive(False)

    def _apply(self, path: str) -> None:
        if self._busy:
            self._toast("Önceki işlem sürüyor, biraz bekle.")
            return
        self._title.set_subtitle("Uygulanıyor…")
        self._run(lambda: gnome.apply_skin(path), "Skin uygulandı")

    def _run(self, job: Callable[[], object], success_message: str | None) -> None:
        self._set_busy(True)

        def work() -> None:
            try:
                job()
                error = None
            except SkinError as failure:
                error = str(failure)
            except Exception as failure:  # shown to the user instead of a silent thread death
                error = f"Beklenmeyen hata: {failure}"
            GLib.idle_add(self._finished, error, success_message)

        threading.Thread(target=work, daemon=True).start()

    def _finished(self, error: str | None, success_message: str | None) -> bool:
        self._set_busy(False)
        self._refresh()
        if error:
            self._toast(error)
        elif success_message:
            self._toast(success_message)
        self._run_pending_size()
        return GLib.SOURCE_REMOVE

    def _on_reset(self, _row) -> None:
        try:
            gnome.reset()
        except Exception as failure:
            self._toast(str(failure))
            return
        self._refresh()
        self._toast("Önceki imlece dönüldü")


def run() -> int:
    application = Adw.Application(application_id=APP_ID)
    application.connect("activate", _present)
    return application.run(sys.argv[:1])


def _present(application: Adw.Application) -> None:
    window = application.get_active_window() or Window(application)
    window.present()
