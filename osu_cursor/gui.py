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
TOAST_MS = 3000
SKIN_LIST_MIN_HEIGHT = 150
BUSY_DIM_MS = 150  # quick jobs finish before anything on screen changes
DROP_HINT = ".osk dosyasını veya skin klasörünü pencereye de bırakabilirsin."
EMPTY_HINT = "Henüz skin yok. Dosya veya klasör seç ya da pencereye bırak."


def _storage_note() -> str:
    folder = str(gnome.skins_dir()).replace(str(Path.home()), "~", 1)
    return (
        "Eklediğin skin'lerin tamamı kopyalanmaz.\n"
        f"Her skin için {folder} içinde bir klasör açılır, "
        "içine sadece imleçle ilgili dosyalar kaydedilir: "
        "cursor, cursormiddle, cursortrail (@2x sürümleriyle) ve skin.ini.\n"
        "Seçtiğin dosyaya veya klasöre dokunulmaz, kaldırınca sadece bu kopya silinir."
    )


def _added_message(counts: tuple[int, int]) -> str:
    added, skipped = counts
    if not added:
        return "Eklenecek yeni skin yok"
    return f"{added} skin eklendi, {skipped} tanesi atlandı" if skipped else f"{added} skin eklendi"


def _import_message(added: int) -> str:
    return f"{added} skin eklendi" if added else "Eklenecek yeni skin yok"


def _searchable(text: str) -> str:
    """Lowercase text that also matches when Turkish i and ı are typed either way."""
    return text.casefold().replace("i̇", "i").replace("ı", "i")


class Window(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application):
        super().__init__(application=application, title="Cursor for osu!")
        self._busy = False
        self._busy_timer = 0
        self._pending_size: float | None = None
        self._pending_apply: str | None = None
        self._size_timer = 0
        self._current_toast: Adw.Toast | None = None
        self._toast_timer = 0
        self._list_version = 0
        self._skin_rows: list[tuple[Adw.ActionRow, str]] = []
        self._skin_checks: list[tuple[str, Gtk.Image]] = []
        self._row_skins: dict[Gtk.ListBoxRow, gnome.LibrarySkin] = {}
        self._menu_skin: gnome.LibrarySkin | None = None

        self._title = Adw.WindowTitle(title="Cursor for osu!")
        self._banner = Adw.Banner(use_markup=False)

        # Only the skin list scrolls, everything above it stays in place.
        skins = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        skins.append(self._build_skins())
        skins.append(self._build_skin_list())
        page = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=18,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )
        settings = self._build_settings()
        page.append(settings)
        page.append(skins)

        self._toasts = Adw.ToastOverlay(child=Adw.Clamp(child=page))
        content = Adw.ToolbarView(content=self._toasts)
        content.add_top_bar(Adw.HeaderBar(title_widget=self._title))
        content.add_top_bar(self._banner)
        content.add_bottom_bar(self._build_reset())
        content.set_bottom_bar_style(Adw.ToolbarStyle.RAISED)
        self.set_content(content)

        # The list is still hidden here, so this is the height of everything else.
        fixed_height = content.measure(Gtk.Orientation.VERTICAL, -1)[0]
        settings_height = settings.measure(Gtk.Orientation.VERTICAL, -1)[1]
        self.set_default_size(560, fixed_height + settings_height * 2)

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
        # The buttons get their own row so the description can use the full width.
        self._skins = Adw.PreferencesGroup(title="Skin'ler", description=DROP_HINT)
        info = Gtk.Image(
            icon_name="dialog-information-symbolic",
            tooltip_text=_storage_note(),
            valign=Gtk.Align.CENTER,
        )
        import_button = Gtk.Button(
            label="Export skin'lerini ekle",
            tooltip_text="osu!lazer'in exports klasöründeki skin'leri listeye ekler",
        )
        import_button.connect("clicked", self._on_import_exports)
        open_button = Gtk.Button(label="Dosya seç")
        folder_button = Gtk.Button(label="Klasör seç")
        folder_button.connect("clicked", self._on_open_folder)
        open_button.connect("clicked", self._on_open)
        self._skins.set_header_suffix(info)
        buttons = Gtk.Box(
            spacing=6,
            margin_top=6,
            margin_bottom=6,
            margin_start=6,
            margin_end=6,
        )
        for button in (import_button, open_button, folder_button):
            button.set_hexpand(True)
        buttons.append(import_button)
        buttons.append(open_button)
        buttons.append(folder_button)
        self._skins.add(Adw.PreferencesRow(child=buttons, activatable=False))

        self._search = Adw.EntryRow(title="Ara")
        self._search.add_prefix(Gtk.Image(icon_name="system-search-symbolic"))
        self._search.connect("changed", lambda _row: self._apply_search())
        self._skins.add(self._search)
        return self._skins

    def _build_skin_list(self) -> Gtk.ScrolledWindow:
        self._skin_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, valign=Gtk.Align.START)
        self._skin_list.add_css_class("boxed-list")
        self._no_match = Adw.ActionRow(title="Eşleşen skin yok", visible=False)
        self._skin_list.append(self._no_match)

        menu = Gio.Menu()
        menu.append("İsmini değiştir", "win.rename-skin")
        menu.append("Dosyasını aç", "win.open-skin")
        self._skin_menu = Gtk.PopoverMenu.new_from_model(menu)
        self._skin_menu.set_has_arrow(False)
        self._skin_menu.set_halign(Gtk.Align.START)
        self._skin_menu.set_parent(self._skin_list)
        for name, callback in (
            ("rename-skin", self._on_rename_skin),
            ("open-skin", self._on_open_skin),
        ):
            action = Gio.SimpleAction(name=name)
            action.connect("activate", callback)
            self.add_action(action)
        right_click = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        right_click.connect("pressed", self._on_skin_right_click)
        self._skin_list.add_controller(right_click)

        self._skin_scroller = Gtk.ScrolledWindow(
            child=self._skin_list,
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            min_content_height=SKIN_LIST_MIN_HEIGHT,
            vexpand=True,
            visible=False,
        )
        return self._skin_scroller

    def _build_reset(self) -> Adw.Clamp:
        self._reset_button = Gtk.Button(
            label="Önceki imlece dön",
            height_request=46,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )
        self._reset_button.connect("clicked", self._on_reset)
        return Adw.Clamp(child=self._reset_button)

    def _load_skins(self) -> None:
        # Readers can finish out of order, only the newest one may fill the list.
        self._list_version += 1
        version = self._list_version

        def work() -> None:
            try:
                skins = gnome.library_skins()
            except Exception as failure:  # shown to the user instead of a silent thread death
                GLib.idle_add(self._toast, f"Skin'ler okunamadı: {failure}")
                return
            GLib.idle_add(self._show_skins, skins, version)

        threading.Thread(target=work, daemon=True).start()

    def _show_skins(self, skins: list[gnome.LibrarySkin], version: int) -> bool:
        if version != self._list_version:
            return GLib.SOURCE_REMOVE
        for row, _name in self._skin_rows:
            self._skin_list.remove(row)
        self._skin_rows.clear()
        self._skin_checks.clear()
        self._row_skins.clear()

        self._skins.set_description(DROP_HINT if skins else EMPTY_HINT)
        for skin in skins:
            row = Adw.ActionRow(
                title=skin.name,
                subtitle="Trail var" if skin.has_trail else "Trail yok",
                title_lines=1,
                subtitle_lines=1,
                use_markup=False,
                activatable=True,
            )
            texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(skin.preview_png))
            row.add_prefix(Gtk.Picture(paintable=texture, can_shrink=False, valign=Gtk.Align.CENTER))
            check = Gtk.Image(icon_name="object-select-symbolic", visible=False)
            row.add_suffix(check)
            remove_button = Gtk.Button(
                icon_name="user-trash-symbolic",
                tooltip_text="Listeden kaldır",
                valign=Gtk.Align.CENTER,
            )
            remove_button.add_css_class("flat")
            remove_button.connect("clicked", self._on_remove_clicked, skin)
            row.add_suffix(remove_button)
            row.connect("activated", self._on_skin_activated, skin.path)
            self._skin_list.append(row)
            self._skin_rows.append((row, _searchable(skin.name)))
            self._row_skins[row] = skin
            self._skin_checks.append((skin.key, check))
        self._apply_search()
        self._refresh()
        return GLib.SOURCE_REMOVE

    def _apply_search(self) -> None:
        query = _searchable(self._search.get_text())
        found = False
        for row, name in self._skin_rows:
            matches = query in name
            row.set_visible(matches)
            found = found or matches
        self._no_match.set_visible(bool(self._skin_rows) and not found)
        self._skin_scroller.set_visible(bool(self._skin_rows))

    def _refresh(self) -> None:
        skin = gnome.current_skin()
        self._title.set_subtitle(" ".join(skin.split()) if skin else "Henüz skin uygulanmadı")

        problem = gnome.trail_problem()
        self._banner.set_title(problem or "")
        self._banner.set_revealed(problem is not None)

        self._reset_button.set_sensitive(skin is not None and not self._busy)
        current = gnome.current_skin_key()
        for key, check in self._skin_checks:
            check.set_visible(key == current)

    def _toast(self, text: str) -> bool:
        """Show one message at a time. A newer one takes the place of the one on screen."""
        title = GLib.markup_escape_text(text)
        if self._current_toast is None:
            # Timed here because the toast's own timer stops while the pointer is over it.
            self._current_toast = Adw.Toast(title=title, timeout=0)
            self._current_toast.connect("dismissed", self._on_toast_dismissed)
            self._toasts.add_toast(self._current_toast)
        else:
            self._current_toast.set_title(title)
        if self._toast_timer:
            GLib.source_remove(self._toast_timer)
        self._toast_timer = GLib.timeout_add(TOAST_MS, self._hide_toast)
        return GLib.SOURCE_REMOVE

    def _hide_toast(self) -> bool:
        self._toast_timer = 0
        if self._current_toast is not None:
            self._current_toast.dismiss()
        return GLib.SOURCE_REMOVE

    def _on_toast_dismissed(self, _toast) -> None:
        if self._toast_timer:
            GLib.source_remove(self._toast_timer)
            self._toast_timer = 0
        self._current_toast = None

    def _on_skin_activated(self, _row, path: Path) -> None:
        self._apply(str(path))

    def _on_drop(self, _target, value, _x, _y) -> bool:
        paths = [file.get_path() for file in value.get_files() if file.get_path()]
        if len(paths) == 1:
            self._add(paths[0])
        elif paths and self._is_free():
            self._run(lambda: gnome.add_skins(paths), _added_message, self._load_skins)
        return bool(paths)

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
            self._add(chosen.get_path())

    def _on_import_exports(self, _button) -> None:
        if self._is_free():
            self._run(gnome.add_exported_skins, _import_message, self._load_skins)

    def _on_open_folder(self, _button) -> None:
        Gtk.FileDialog(title="Skin klasörü seç").select_folder(self, None, self._on_folder_chosen)

    def _on_folder_chosen(self, dialog, result) -> None:
        try:
            chosen = dialog.select_folder_finish(result)
        except GLib.Error:
            return  # the dialog was cancelled
        if chosen.get_path():
            self._add(chosen.get_path())

    def _on_skin_right_click(self, _gesture, _presses, x: float, y: float) -> None:
        skin = self._row_skins.get(self._skin_list.get_row_at_y(int(y)))
        if skin is None:
            return
        self._menu_skin = skin
        point = Gdk.Rectangle()
        point.x, point.y, point.width, point.height = int(x), int(y), 1, 1
        self._skin_menu.set_pointing_to(point)
        self._skin_menu.popup()

    def _on_rename_skin(self, _action, _parameter) -> None:
        skin = self._menu_skin
        if skin is None:
            return
        entry = Gtk.Entry(text=skin.name, activates_default=True)
        dialog = Adw.AlertDialog(heading="Skin'in ismini değiştir", extra_child=entry)
        dialog.add_response("cancel", "Vazgeç")
        dialog.add_response("rename", "Değiştir")
        dialog.set_response_appearance("rename", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("rename")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_rename_response, entry, skin.path)
        dialog.present(self)

    def _on_rename_response(self, _dialog, response: str, entry: Gtk.Entry, path: Path) -> None:
        if response == "rename" and self._is_free():
            name = entry.get_text()
            self._run(lambda: gnome.rename_skin(path, name), "İsim değiştirildi", self._load_skins)

    def _on_open_skin(self, _action, _parameter) -> None:
        if self._menu_skin is None:
            return
        launcher = Gtk.FileLauncher(file=Gio.File.new_for_path(str(self._menu_skin.path)))
        launcher.launch(self, None, self._on_folder_opened)

    def _on_folder_opened(self, launcher, result) -> None:
        try:
            launcher.launch_finish(result)
        except GLib.Error as failure:
            self._toast(f"Klasör açılamadı: {failure.message}")

    def _on_remove_clicked(self, _button, skin: gnome.LibrarySkin) -> None:
        dialog = Adw.AlertDialog(
            heading="Skin kaldırılsın mı?",
            body=(
                f"{skin.name} listeden silinir ve önceki imlece dönülür."
                if skin.key == gnome.current_skin_key()
                else f"{skin.name} listeden silinir. Şu an kullandığın imleç değişmez."
            ),
        )
        dialog.add_response("cancel", "Vazgeç")
        dialog.add_response("remove", "Kaldır")
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_remove_response, skin.path)
        dialog.present(self)

    def _on_remove_response(self, _dialog, response: str, path: Path) -> None:
        if response == "remove" and self._is_free():
            self._run(lambda: gnome.remove_skin(path), "Skin kaldırıldı", self._load_skins)

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
        if self._busy_timer:
            GLib.source_remove(self._busy_timer)
            self._busy_timer = 0
        if busy:
            self._busy_timer = GLib.timeout_add(BUSY_DIM_MS, self._dim_controls)
        else:
            self._set_controls_sensitive(True)

    def _dim_controls(self) -> bool:
        self._busy_timer = 0
        self._set_controls_sensitive(False)
        return GLib.SOURCE_REMOVE

    def _set_controls_sensitive(self, sensitive: bool) -> None:
        self._skins.set_sensitive(sensitive)
        self._skin_list.set_sensitive(sensitive)
        self._trail_row.set_sensitive(sensitive)
        if not sensitive:
            self._reset_button.set_sensitive(False)

    def _is_free(self) -> bool:
        if self._busy:
            self._toast("Önceki işlem sürüyor, biraz bekle.")
        return not self._busy

    def _add(self, path: str) -> None:
        if self._is_free():
            self._run(lambda: gnome.add_skin(path), "Skin listeye eklendi", self._load_skins)

    def _apply(self, path: str) -> None:
        if self._busy:
            self._pending_apply = path  # only the skin clicked last matters
            return
        self._run(lambda: gnome.apply_skin(path), None)

    def _run(
        self,
        job: Callable[[], object],
        success_message: str | Callable[..., str] | None,
        after_success: Callable[[], None] | None = None,
    ) -> None:
        self._set_busy(True)

        def work() -> None:
            message = success_message
            try:
                result = job()
                error = None
                if callable(success_message):
                    message = success_message(result)
            except SkinError as failure:
                error = str(failure)
            except Exception as failure:  # shown to the user instead of a silent thread death
                error = f"Beklenmeyen hata: {failure}"
            GLib.idle_add(self._finished, error, message, after_success)

        threading.Thread(target=work, daemon=True).start()

    def _finished(
        self,
        error: str | None,
        success_message: str | None,
        after_success: Callable[[], None] | None,
    ) -> bool:
        self._set_busy(False)
        self._refresh()
        if error:
            self._toast(error)
        else:
            if success_message:
                self._toast(success_message)
            if after_success:
                after_success()
        self._run_pending_size()
        if self._pending_apply is not None and not self._busy:
            path, self._pending_apply = self._pending_apply, None
            self._apply(path)
        return GLib.SOURCE_REMOVE

    def _on_reset(self, _button) -> None:
        if self._is_free():
            self._run(gnome.reset, "Önceki imlece dönüldü")


def run() -> int:
    application = Adw.Application(application_id=APP_ID)
    application.connect("activate", _present)
    return application.run(sys.argv[:1])


def _present(application: Adw.Application) -> None:
    window = application.get_active_window() or Window(application)
    window.present()
