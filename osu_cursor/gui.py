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
from .i18n import _  # noqa: E402
from .skin import SkinError  # noqa: E402

APP_ID = "io.github.egehankara.CursorForOsu"
SIZE_SETTLE_MS = 300
TOAST_MS = 3000
SKIN_LIST_MIN_HEIGHT = 150
BUSY_DIM_MS = 150  # quick jobs finish before anything on screen changes
EXPORT_SETTLE_MS = 1000  # the game writes an export in several steps
DROP_HINT = _("You can also drop .osk files and skin folders on the window.")
EMPTY_HINT = _("No skins yet. Choose an .osk file or a folder, or drop them on the window.")


def _storage_note() -> str:
    folder = str(gnome.skins_dir()).replace(str(Path.home()), "~", 1)
    return _(
        "The skins you add are not copied whole.\n"
        "Each skin gets a folder in {folder} that holds only the cursor files: "
        "cursor, cursormiddle, cursortrail (with their @2x versions) and skin.ini.\n"
        "The file or folder you chose is left alone, removing a skin only deletes this copy."
    ).format(folder=folder)


def _added_message(counts: tuple[int, int]) -> str:
    added, skipped = counts
    if not added:
        return _("No new skins to add")
    if skipped:
        return _("Skins added: {added}, skipped: {skipped}").format(added=added, skipped=skipped)
    return _("Skins added: {added}").format(added=added)


def _all_exports_message(added: int) -> str:
    if not added:
        return _("No new skins, all of them are already in the list")
    return _("Skins added: {added}").format(added=added)


def _exports_message(added: int) -> str:
    return _("New skins from osu!lazer: {added}").format(added=added)


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
        # Jobs that change the skin library take turns, the export watcher runs beside them.
        self._library_lock = threading.Lock()
        self._exports_timer = 0
        self._scanning_exports = False
        self._exports_pending = False
        self._exports_monitor: Gio.FileMonitor | None = None

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
        if self._watch_switch.get_active():
            self._watch_exports()

    def _build_settings(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title=_("Settings"))

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
        size_row = Adw.ActionRow(title=_("Cursor size"))
        size_row.add_suffix(self._size_scale)
        group.add(size_row)

        if gnome.has_game_cursor_size():
            game_size = gnome.game_cursor_size()
            use_button = Gtk.Button(label=_("Use"), valign=Gtk.Align.CENTER)
            use_button.connect("clicked", lambda _button: self._size_scale.set_value(game_size))
            game_row = Adw.ActionRow(
                title=_("In-game size"),
                subtitle=_("Your osu!lazer setting: {size}").format(size=f"{game_size:.2f}"),
            )
            game_row.add_suffix(use_button)
            group.add(game_row)

        self._trail_row = Adw.SwitchRow(
            title=_("Trail"),
            subtitle=_("When off, only the cursor is left"),
            active=gnome.trail_enabled(),
        )
        self._trail_row.connect("notify::active", self._on_trail_toggled)
        group.add(self._trail_row)

        self._system_row = Adw.SwitchRow(
            title=_("Keep system cursors"),
            subtitle=_("Text and resize cursors stay, in the skin's colour"),
            tooltip_text=_(
                "When on, the text cursor (I), the window resize and move arrows, "
                "the not-allowed sign and the crosshair don't turn into the osu! cursor, "
                "they come from the cursor theme you used before the skin.\n"
                "They are painted in the colour of the skin cursor. Each has a dark and a light shade, "
                "so they stay visible on light and dark backgrounds. No trail is drawn behind them.\n"
                "The normal arrow, the hand over clickable things and the busy cursor stay the osu! cursor."
            ),
            active=gnome.keep_system_cursors(),
        )
        self._system_row.connect("notify::active", self._on_system_toggled)
        group.add(self._system_row)

        exports = str(gnome.exports_dir()).replace(str(Path.home()), "~", 1)
        # A plain row with its own switch, so the button can sit before the switch.
        self._watch_switch = Gtk.Switch(active=gnome.watch_exports_enabled(), valign=Gtk.Align.CENTER)
        self._watch_switch.connect("notify::active", self._on_watch_toggled)
        watch_row = Adw.ActionRow(
            title=_("Watch osu! exports"),
            subtitle=(
                _("Skins you export from the game are added to the list on their own")
                if gnome.osu_dir().is_dir()
                else _("osu!lazer was not found. Exports are added once it is installed.")
            ),
            tooltip_text=_(
                "While the app is open it watches osu!lazer's exports folder ({folder}) "
                "and adds each skin you export to the list.\n"
                "Exports made while the app is closed are added the next time it opens.\n"
                "A skin you remove from the list doesn't come back unless you export it again."
            ).format(folder=exports),
            activatable_widget=self._watch_switch,
        )
        add_all_button = Gtk.Button(
            icon_name="list-add-symbolic",
            tooltip_text=_(
                "Adds every skin in the exports folder to the list now, "
                "including the ones you removed before.\n"
                "Skins already in the list are not added twice."
            ),
            valign=Gtk.Align.CENTER,
        )
        add_all_button.add_css_class("flat")
        add_all_button.connect("clicked", self._on_add_all_exports)
        watch_row.add_suffix(add_all_button)
        watch_row.add_suffix(self._watch_switch)
        group.add(watch_row)
        return group

    def _build_skins(self) -> Adw.PreferencesGroup:
        # The buttons get their own row so the description can use the full width.
        self._skins = Adw.PreferencesGroup(title=_("Skins"), description=DROP_HINT)
        info = Gtk.Image(
            icon_name="dialog-information-symbolic",
            tooltip_text=_storage_note(),
            valign=Gtk.Align.CENTER,
        )
        open_button = Gtk.Button(
            label=_("Choose .osk"),
            tooltip_text=_("A skin packed in one file, like an .osk you downloaded or exported"),
        )
        folder_button = Gtk.Button(
            label=_("Choose folder"),
            tooltip_text=_("An unpacked skin folder, like a skin in osu! stable's Skins folder"),
        )
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
        for button in (open_button, folder_button):
            button.set_hexpand(True)
        buttons.append(open_button)
        buttons.append(folder_button)
        self._skins.add(Adw.PreferencesRow(child=buttons, activatable=False))

        self._search = Adw.EntryRow(title=_("Search"))
        self._search.add_prefix(Gtk.Image(icon_name="system-search-symbolic"))
        self._search.connect("changed", lambda _row: self._apply_search())
        self._skins.add(self._search)
        return self._skins

    def _build_skin_list(self) -> Gtk.ScrolledWindow:
        self._skin_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, valign=Gtk.Align.START)
        self._skin_list.add_css_class("boxed-list")
        self._skin_list.set_placeholder(self._build_no_match())

        menu = Gio.Menu()
        menu.append(_("Rename"), "win.rename-skin")
        menu.append(_("Open its folder"), "win.open-skin")
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

    def _build_no_match(self) -> Gtk.Box:
        """Shown inside the list when the search hides every skin."""
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=6,
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.CENTER,
            margin_top=30,
            margin_bottom=30,
            margin_start=12,
            margin_end=12,
        )
        icon = Gtk.Image(icon_name="system-search-symbolic", pixel_size=40, margin_bottom=6)
        icon.add_css_class("dim-label")
        title = Gtk.Label(label=_("No matching skins"))
        title.add_css_class("title-4")
        self._no_match_query = Gtk.Label(
            wrap=True, justify=Gtk.Justification.CENTER, max_width_chars=40
        )
        self._no_match_query.add_css_class("dim-label")
        box.append(icon)
        box.append(title)
        box.append(self._no_match_query)
        return box

    def _build_reset(self) -> Adw.Clamp:
        self._reset_button = Gtk.Button(
            label=_("Go back to the previous cursor"),
            height_request=46,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )
        self._reset_button.connect("clicked", self._on_reset)
        return Adw.Clamp(child=self._reset_button)

    def _on_system_toggled(self, row, _param) -> None:
        active = row.get_active()
        if active == gnome.keep_system_cursors():
            return  # put back after a refused change
        if not self._is_free():
            row.set_active(not active)
            return
        self._run(lambda: gnome.set_keep_system_cursors(active), None)

    def _on_watch_toggled(self, row, _param) -> None:
        try:
            gnome.set_watch_exports_enabled(row.get_active())
        except OSError as failure:
            self._toast(str(failure))
        if row.get_active():
            self._watch_exports()
        else:
            self._stop_watching_exports()

    def _stop_watching_exports(self) -> None:
        if self._exports_monitor is not None:
            self._exports_monitor.cancel()
            self._exports_monitor = None
        if self._exports_timer:
            GLib.source_remove(self._exports_timer)
            self._exports_timer = 0
        self._exports_pending = False

    def _watch_exports(self) -> None:
        """Add skins exported from osu!lazer, now and whenever a new one appears."""
        exports = Gio.File.new_for_path(str(gnome.exports_dir()))
        try:
            # GLib keeps watching a folder that doesn't exist yet and notices when it appears.
            self._exports_monitor = exports.monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
        except GLib.Error:
            self._exports_monitor = None
        else:
            self._exports_monitor.connect("changed", self._on_exports_changed)
        self._scan_exports()

    def _on_exports_changed(self, *_args) -> None:
        if self._exports_timer:
            GLib.source_remove(self._exports_timer)
        self._exports_timer = GLib.timeout_add(EXPORT_SETTLE_MS, self._scan_exports)

    def _scan_exports(self) -> bool:
        self._exports_timer = 0
        if not self._watch_switch.get_active():
            return GLib.SOURCE_REMOVE
        if self._scanning_exports:
            self._exports_pending = True  # look again once the running scan is done
            return GLib.SOURCE_REMOVE
        self._scanning_exports = True

        def work() -> None:
            try:
                with self._library_lock:
                    added = gnome.add_new_exports()
                error = None
            except Exception as failure:  # shown to the user instead of a silent thread death
                added, error = 0, _("Couldn't read the osu!lazer exports: {error}").format(error=failure)
            GLib.idle_add(self._exports_scanned, added, error)

        threading.Thread(target=work, daemon=True).start()
        return GLib.SOURCE_REMOVE

    def _exports_scanned(self, added: int, error: str | None) -> bool:
        self._scanning_exports = False
        if error:
            self._toast(error)
        elif added:
            self._toast(_exports_message(added))
            self._load_skins()
        if self._exports_pending:
            self._exports_pending = False
            self._scan_exports()
        return GLib.SOURCE_REMOVE

    def _load_skins(self) -> None:
        # Readers can finish out of order, only the newest one may fill the list.
        self._list_version += 1
        version = self._list_version

        def work() -> None:
            try:
                skins = gnome.library_skins()
            except Exception as failure:  # shown to the user instead of a silent thread death
                GLib.idle_add(self._toast, _("Couldn't read the skins: {error}").format(error=failure))
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
                subtitle=_("Has a trail") if skin.has_trail else _("No trail"),
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
                tooltip_text=_("Remove from the list"),
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
        # With nothing to show, the list fills its space so the message sits in the middle.
        self._skin_list.set_valign(Gtk.Align.START if found else Gtk.Align.FILL)
        # No card behind the message, it sits right on the window.
        if found:
            self._skin_list.remove_css_class("no-match")
            self._skin_list.add_css_class("boxed-list")
        else:
            self._skin_list.remove_css_class("boxed-list")
            self._skin_list.add_css_class("no-match")
        if not found:
            # The list shows its placeholder by itself once every row is hidden.
            self._no_match_query.set_label(
                _("Nothing found for “{query}”").format(query=self._search.get_text().strip())
            )
        self._skin_scroller.set_visible(bool(self._skin_rows))

    def _refresh(self) -> None:
        skin = gnome.current_skin()
        self._title.set_subtitle(" ".join(skin.split()) if skin else _("No skin applied yet"))

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
        dialog = Gtk.FileDialog(title=_("Choose a skin"), filters=filters)
        dialog.open(self, None, self._on_chosen)

    def _on_chosen(self, dialog, result) -> None:
        try:
            chosen = dialog.open_finish(result)
        except GLib.Error:
            return  # the dialog was cancelled
        if chosen.get_path():
            self._add(chosen.get_path())

    def _on_add_all_exports(self, _button) -> None:
        if not gnome.osu_dir().is_dir():
            self._toast(_("osu!lazer was not found on this computer."))
        elif not gnome.exports_dir().is_dir():
            self._toast(_("You haven't exported any skins from osu!lazer yet."))
        elif self._is_free():
            self._run(lambda: gnome.add_new_exports(everything=True), _all_exports_message, self._load_skins)

    def _on_open_folder(self, _button) -> None:
        Gtk.FileDialog(title=_("Choose a skin folder")).select_folder(self, None, self._on_folder_chosen)

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
        dialog = Adw.AlertDialog(heading=_("Rename the skin"), extra_child=entry)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("rename", _("Rename"))
        dialog.set_response_appearance("rename", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("rename")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_rename_response, entry, skin.path)
        dialog.present(self)

    def _on_rename_response(self, _dialog, response: str, entry: Gtk.Entry, path: Path) -> None:
        if response == "rename" and self._is_free():
            name = entry.get_text()
            self._run(lambda: gnome.rename_skin(path, name), _("Renamed"), self._load_skins)

    def _on_open_skin(self, _action, _parameter) -> None:
        if self._menu_skin is None:
            return
        launcher = Gtk.FileLauncher(file=Gio.File.new_for_path(str(self._menu_skin.path)))
        launcher.launch(self, None, self._on_folder_opened)

    def _on_folder_opened(self, launcher, result) -> None:
        try:
            launcher.launch_finish(result)
        except GLib.Error as failure:
            self._toast(_("Couldn't open the folder: {error}").format(error=failure.message))

    def _on_remove_clicked(self, _button, skin: gnome.LibrarySkin) -> None:
        dialog = Adw.AlertDialog(
            heading=_("Remove the skin?"),
            body=(
                _("{name} is removed from the list and the previous cursor comes back.")
                if skin.key == gnome.current_skin_key()
                else _("{name} is removed from the list. The cursor you use now stays.")
            ).format(name=skin.name),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("remove", _("Remove"))
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_remove_response, skin.path)
        dialog.present(self)

    def _on_remove_response(self, _dialog, response: str, path: Path) -> None:
        if response == "remove" and self._is_free():
            self._run(lambda: gnome.remove_skin(path), _("Skin removed"), self._load_skins)

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
        self._system_row.set_sensitive(sensitive)
        if not sensitive:
            self._reset_button.set_sensitive(False)

    def _is_free(self) -> bool:
        if self._busy:
            self._toast(_("The previous task is still running, wait a moment."))
        return not self._busy

    def _add(self, path: str) -> None:
        if self._is_free():
            self._run(lambda: gnome.add_skin(path), _("Skin added to the list"), self._load_skins)

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
                with self._library_lock:
                    result = job()
                error = None
                if callable(success_message):
                    message = success_message(result)
            except SkinError as failure:
                error = str(failure)
            except Exception as failure:  # shown to the user instead of a silent thread death
                error = _("Unexpected error: {error}").format(error=failure)
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
            self._run(gnome.reset, _("Back to the previous cursor"))


def run() -> int:
    application = Adw.Application(application_id=APP_ID)
    application.connect("startup", _add_style)
    application.connect("activate", _present)
    return application.run(sys.argv[:1])


def _add_style(_application: Adw.Application) -> None:
    Gtk.Window.set_default_icon_name(APP_ID)  # installed by install.sh, named after the app
    css = Gtk.CssProvider()
    css.load_from_string("list.no-match { background: none; }")
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )


def _present(application: Adw.Application) -> None:
    window = application.get_active_window() or Window(application)
    window.present()
