"""The window: pick a skin, set the cursor size and turn the trail on or off."""

from __future__ import annotations

import locale
import shlex
import sys
import threading
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Graphene, Gsk, Gtk, Pango  # noqa: E402

from . import __version__, gnome, plasma, update  # noqa: E402
from .i18n import _  # noqa: E402
from .skin import SkinError  # noqa: E402

APP_ID = "io.github.egehankara.CursorForOsu"
TOAST_MS = 3000
HIGHLIGHT_MS = 1600  # how long a card just added, or found already there, stands out
# While the size slider is dragged. Each step makes GNOME reload the cursor in every app.
SIZE_INTERVAL_MS = 100
PAGE_MARGIN = 16
WINDOW_SIZE = (560, 780)
STAGE_HEIGHT = 84  # the dark strip of a skin card the cursor is shown on
COMMANDS_MAX_CHARS = 52  # the update commands, so the dialog fits the window
UPDATES_ON_LINK = "cursor-for-osu:updates-on"  # handled in the window, never opened
BUSY_DIM_MS = 150  # quick jobs finish before anything on screen changes
EXPORT_SETTLE_MS = 1000  # the game writes an export in several steps
DROP_HINT = _("Drop skins on the window to add them")
EMPTY_HINT = _("No skins yet. Choose an .osk file or a folder, or drop them on the window.")


# Night purple with a pink accent. One palette everywhere, so the window looks
# the same on GNOME and KDE Plasma instead of borrowing one desktop's style.
PALETTE = {
    "bg": "#15111c",
    "panel": "#1d1726",
    "raised": "#241d30",
    "stage": "#0f0b15",
    "line": "#2a2236",
    "line-strong": "#3a3049",
    "fg": "#efe9f4",
    "muted": "#958aa6",
    "accent": "#ff5fa2",
    "accent-text": "#ff8cbd",
    "accent-ink": "#2a0c1a",
}


class _Preview(Gtk.Widget):
    """A skin picture shown at half its pixel size, so it stays sharp on scaled screens.

    It shrinks with the window, keeping its shape.
    """

    def __init__(self, texture: Gdk.Texture):
        super().__init__(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, hexpand=True)
        self._texture = texture
        self._size = (texture.get_width() // 2, texture.get_height() // 2)

    def do_measure(self, orientation, _for_size):
        natural = self._size[0] if orientation == Gtk.Orientation.HORIZONTAL else self._size[1]
        return natural // 2, natural, -1, -1

    def do_snapshot(self, snapshot):
        width, height = self.get_width(), self.get_height()
        scale = min(width / self._size[0], height / self._size[1], 1)
        shown_width, shown_height = self._size[0] * scale, self._size[1] * scale
        area = Graphene.Rect().init(
            (width - shown_width) / 2, (height - shown_height) / 2, shown_width, shown_height
        )
        snapshot.append_scaled_texture(self._texture, Gsk.ScalingFilter.TRILINEAR, area)


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


def _shell_path(path: Path) -> str:
    """A path to type in a shell, with ~ for the home folder like the README shows."""
    try:
        inside_home = path.relative_to(Path.home())
    except ValueError:
        return shlex.quote(str(path))
    return "~/" + shlex.quote(str(inside_home)) if str(inside_home) != "." else "~"


def _number(value: float, digits: int | None = 2) -> str:
    """A number written the local way, 0,38 in Turkish and 0.38 in English."""
    text = f"{value:.{digits}f}" if digits is not None else str(value)
    return text.replace(".", locale.localeconv()["decimal_point"] or ".")


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
        self._skin_rows: list[tuple[Gtk.FlowBoxChild, str]] = []
        self._skin_checks: list[tuple[str, Gtk.Image, Gtk.Widget]] = []
        self._row_skins: dict[Gtk.FlowBoxChild, gnome.LibrarySkin] = {}
        self._menu_skin: gnome.LibrarySkin | None = None
        # The card to scroll to once the list is filled: the skin just added, or the one
        # that was already there. Set by a background job, read on the main thread.
        self._reveal_key: str | None = None
        self._highlight: tuple[Gtk.Widget, int] | None = None  # the card and its timer
        # Jobs that change the skin library take turns, the export watcher runs beside them.
        self._library_lock = threading.Lock()
        self._exports_timer = 0
        self._scanning_exports = False
        self._exports_pending = False
        self._exports_monitor: Gio.FileMonitor | None = None

        self._title = Adw.WindowTitle(title="Cursor for osu!")  # the applied skin is marked on its card
        self._banner = Adw.Banner(use_markup=False)
        self._update: update.Release | None = None
        self._update_banner = Adw.Banner(use_markup=False, button_label=_("How to update"))
        self._update_banner.connect("button-clicked", lambda _banner: self._show_update_dialog())

        # Only the skin cards scroll, everything above them stays in place. The right
        # margin is left to each part, so the cards' scrollbar can sit in it and the
        # cards line up with the parts above.
        page = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=14,
            margin_top=PAGE_MARGIN,
            margin_start=PAGE_MARGIN,
        )
        for part in (self._build_settings(), self._build_skins()):
            part.set_margin_end(PAGE_MARGIN)
            page.append(part)
        page.append(self._build_skin_list())

        # Covers the page while files are dragged over the window, saying where to drop them.
        self._drop_zone = self._build_drop_zone()
        with_drop_zone = Gtk.Overlay(child=page)
        with_drop_zone.add_overlay(self._drop_zone)
        self._toasts = Adw.ToastOverlay(child=Adw.Clamp(child=with_drop_zone, maximum_size=900))
        self._toasts.add_css_class("drop-target")
        content = Adw.ToolbarView(content=self._toasts)
        header = Adw.HeaderBar(title_widget=self._title)
        about_button = Gtk.Button(icon_name="help-about-symbolic", tooltip_text=_("About Cursor for osu!"))
        about_button.connect("clicked", lambda _button: self._show_about())
        # Opens the settings changed once and left alone, right under the size. Closed at start.
        self._more_button = Gtk.ToggleButton(icon_name="emblem-system-symbolic", tooltip_text=_("More settings"))
        self._more_button.bind_property("active", self._more_settings, "reveal-child", 0)
        header.pack_end(about_button)
        header.pack_end(self._more_button)
        content.add_top_bar(header)
        content.add_top_bar(self._banner)
        content.add_top_bar(self._update_banner)
        content.set_top_bar_style(Adw.ToolbarStyle.RAISED_BORDER)
        content.add_bottom_bar(self._build_reset())
        self.set_content(content)
        self.set_default_size(*WINDOW_SIZE)

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("enter", self._on_drag_enter)
        drop.connect("leave", lambda _target: self._drop_zone.set_reveal_child(False))
        drop.connect("drop", self._on_drop)
        self._toasts.add_controller(drop)

        self._refresh()
        self._load_skins()
        if self._watch_switch.get_active():
            self._watch_exports()
        self._check_for_update()

    def _build_settings(self) -> Gtk.Box:
        """Size and trail in one line, with the rarely changed settings folded under them."""
        self._size_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, gnome.MIN_CURSOR_SIZE, gnome.MAX_CURSOR_SIZE, 0.01
        )
        self._size_scale.set_draw_value(False)
        self._size_scale.set_hexpand(True)
        self._size_scale.set_valign(Gtk.Align.CENTER)
        self._size_scale.set_tooltip_text(_("Cursor size"))
        self._size_scale.add_css_class("size")
        self._size_scale.set_value(gnome.cursor_size())
        # The number can be clicked and typed over, Enter or clicking away applies it.
        self._size_value = Gtk.Entry(
            width_chars=4, max_width_chars=4, xalign=1, valign=Gtk.Align.CENTER,
            input_purpose=Gtk.InputPurpose.NUMBER, tooltip_text=_("Click to type a size"),
        )
        self._size_value.add_css_class("numeric")
        self._size_value.add_css_class("size-entry")
        self._size_value.connect("activate", lambda _entry: self._type_size())
        focus = Gtk.EventControllerFocus()
        focus.connect("leave", lambda _controller: self._type_size())
        self._size_value.add_controller(focus)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_size_key)
        self._size_value.add_controller(keys)
        self._show_size()
        self._size_scale.connect("value-changed", self._on_size_changed)

        self._trail_switch = Gtk.Switch(
            active=gnome.trail_enabled(),
            valign=Gtk.Align.CENTER,
            tooltip_text=_("When off, only the cursor is left"),
        )
        self._trail_switch.connect("notify::active", self._on_trail_toggled)

        line = Gtk.Box(spacing=12)
        line.add_css_class("controls-line")
        size_label = Gtk.Label(label=_("Size"))
        trail_label = Gtk.Label(label=_("Trail"), margin_start=8)
        for label in (size_label, trail_label):
            label.add_css_class("dimmed")
        for widget in (size_label, self._size_scale, self._size_value, trail_label, self._trail_switch):
            line.append(widget)

        more = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        more.add_css_class("more-settings")
        for row in self._build_more_settings():
            more.append(row)
        self._more_settings = Gtk.Revealer(
            child=more, transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN
        )

        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        panel.add_css_class("controls")
        panel.append(line)
        panel.append(self._more_settings)
        return panel

    def _show_size(self, while_typing: bool = False) -> None:
        # The entry's text field inside it holds the focus, not the entry itself.
        typing = self._size_value.get_state_flags() & Gtk.StateFlags.FOCUS_WITHIN
        if typing and not while_typing:
            return  # don't write over what is being typed
        self._size_value.set_text(_number(self._size_scale.get_value()))

    def _type_size(self) -> None:
        """Use the typed size. Both 0,5 and 0.5 work, out of range is brought into range."""
        text = self._size_value.get_text().strip().replace(",", ".")
        try:
            size = round(float(text), 2)
        except ValueError:
            self._show_size(while_typing=True)  # not a number, put the size back
            return
        clamped = gnome.clamp_cursor_size(size)
        if clamped != size:
            self._toast(_("The size has to be between {low} and {high}.").format(
                low=_number(gnome.MIN_CURSOR_SIZE, None), high=_number(gnome.MAX_CURSOR_SIZE, None)))
        self._size_scale.set_value(clamped)
        self._show_size(while_typing=True)

    def _on_size_key(self, _controller, keyval, _keycode, _state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self._show_size(while_typing=True)  # give up the typed text
            self._size_scale.grab_focus()
            return True
        return False

    def _build_more_settings(self) -> list[Gtk.Widget]:
        """The settings changed once and left alone, folded away under More settings."""
        rows: list[Gtk.Widget] = []

        # For people who keep osu!lazer somewhere the app doesn't look.
        self._osu_row = Adw.ActionRow(title=_("osu!lazer folder"), subtitle_lines=1)
        self._osu_auto_button = Gtk.Button(
            icon_name="edit-undo-symbolic",
            tooltip_text=_("Find it on its own again"),
            valign=Gtk.Align.CENTER,
        )
        self._osu_auto_button.add_css_class("flat")
        self._osu_auto_button.connect("clicked", lambda _button: self._set_osu_dir(None))
        # Not "Choose folder", that button is right below for adding skins.
        choose_button = Gtk.Button(label=_("Change"), valign=Gtk.Align.CENTER)
        choose_button.connect("clicked", self._on_choose_osu_dir)
        self._osu_row.add_suffix(self._osu_auto_button)
        self._osu_row.add_suffix(choose_button)

        # Always built, it is shown once the chosen folder has the game's settings.
        use_button = Gtk.Button(label=_("Use"), valign=Gtk.Align.CENTER)
        use_button.connect(
            "clicked", lambda _button: self._size_scale.set_value(gnome.game_cursor_size())
        )
        self._game_row = Adw.ActionRow(title=_("In-game size"))
        self._game_row.add_suffix(use_button)
        rows.append(self._game_row)

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
        rows.append(self._system_row)

        # A plain row with its own switch, so the button can sit before the switch.
        self._watch_switch = Gtk.Switch(active=gnome.watch_exports_enabled(), valign=Gtk.Align.CENTER)
        self._watch_switch.connect("notify::active", self._on_watch_toggled)
        self._watch_row = watch_row = Adw.ActionRow(
            title=_("Watch osu! exports"),
            activatable_widget=self._watch_switch,
        )
        add_all_button = Gtk.Button(
            label=_("Add all"),
            tooltip_text=_(
                "Adds every skin in the exports folder to the list now, "
                "including the ones you removed before.\n"
                "Skins already in the list are not added twice."
            ),
            valign=Gtk.Align.CENTER,
        )
        add_all_button.connect("clicked", self._on_add_all_exports)
        watch_row.add_suffix(add_all_button)
        watch_row.add_suffix(self._watch_switch)
        rows.append(watch_row)
        rows.append(self._osu_row)

        self._show_osu_dir()
        return rows

    def _show_osu_dir(self) -> None:
        """Fill in the rows that depend on where osu!lazer is."""
        home = str(Path.home())
        folder = gnome.osu_dir()
        found = folder.is_dir()
        self._osu_row.set_subtitle(
            str(folder).replace(home, "~", 1) if found
            else _("Not found. Choose it if osu!lazer keeps its files somewhere else.")
        )
        # A long path is cut short, the explanation is shown whole.
        self._osu_row.set_subtitle_lines(1 if found else 0)
        self._osu_auto_button.set_visible(gnome.chosen_osu_dir() is not None)

        self._game_row.set_visible(gnome.has_game_cursor_size())
        self._game_row.set_subtitle(
            _("Your osu!lazer setting: {size}").format(size=_number(gnome.game_cursor_size()))
        )

        self._watch_row.set_subtitle(
            _("Skins you export from the game are added to the list on their own")
            if found
            else _("osu!lazer was not found. Exports are added once it is installed.")
        )
        self._watch_row.set_tooltip_text(_(
            "While the app is open it watches osu!lazer's exports folder ({folder}) "
            "and adds each skin you export to the list.\n"
            "Exports made while the app is closed are added the next time it opens.\n"
            "A skin you remove from the list doesn't come back unless you export it again."
        ).format(folder=str(gnome.exports_dir()).replace(home, "~", 1)))

    def _on_choose_osu_dir(self, _button) -> None:
        dialog = Gtk.FileDialog(title=_("Choose the osu!lazer folder"))
        folder = gnome.osu_dir()
        if folder.is_dir():
            dialog.set_initial_folder(Gio.File.new_for_path(str(folder)))
        dialog.select_folder(self, None, self._on_osu_dir_chosen)

    def _on_osu_dir_chosen(self, dialog, result) -> None:
        try:
            chosen = dialog.select_folder_finish(result)
        except GLib.Error:
            return  # the dialog was cancelled
        if chosen.get_path():
            self._set_osu_dir(chosen.get_path())

    def _set_osu_dir(self, path: str | None) -> None:
        try:
            gnome.set_osu_dir(path)
        except (SkinError, OSError) as failure:
            self._toast(str(failure))
            return
        self._show_osu_dir()
        # The exports of the new folder are looked at right away.
        if self._watch_switch.get_active():
            self._stop_watching_exports()
            self._watch_exports()

    def _check_for_update(self) -> None:
        """Ask GitHub for the latest version without holding up the window."""
        def work() -> None:
            try:
                release = update.available_update()
            except Exception:  # a failed check is not worth bothering anyone with
                release = None
            GLib.idle_add(self._update_found, release)

        threading.Thread(target=work, daemon=True).start()

    def _update_found(self, release: update.Release | None) -> bool:
        self._update = release
        self._refresh()
        return GLib.SOURCE_REMOVE

    def _show_update_dialog(self) -> None:
        release = self._update
        if release is None:
            return
        folder = update.source_dir()
        lines = [
            f"cd {_shell_path(folder)}" if folder else "cd cursor-for-osu",
            "git pull",
            "bash install.sh",
        ]
        if plasma.selected():
            # The KWin effect is built on the computer, like in step 3 of the README.
            lines += [
                "cmake -S kwin -B build \\",
                f"    -DKDE_INSTALL_PLUGINDIR={plasma.qt_plugin_dir_argument()}",
                "cmake --build build",
                "sudo cmake --install build",
            ]
            after = _("Then log out and back in once, so the new trail effect is loaded.")
        else:
            after = _("Then log out and back in once, so the new trail extension is loaded.")
        commands = "\n".join(lines)
        dialog = Adw.AlertDialog(
            heading=_("Version {version} is out").format(version=release.version),
            body=_("You have {current}. Run these in a terminal:").format(current=__version__),
        )
        if hasattr(dialog.props, "prefer_wide_layout"):  # libadwaita 1.6 and newer
            dialog.set_prefer_wide_layout(True)

        # Not selectable, it would open with everything selected. The button copies it.
        # As wide as the longest command, up to a limit. Only a very long folder wraps,
        # and without hyphens, which would read as part of the command.
        width = min(max(len(line) for line in lines), COMMANDS_MAX_CHARS)
        label = Gtk.Label(
            label=commands, xalign=0, hexpand=True, wrap=True, wrap_mode=Pango.WrapMode.CHAR,
            width_chars=width, max_width_chars=width,
            margin_top=12, margin_bottom=12, margin_start=14,
        )
        no_hyphens = Pango.AttrList()
        no_hyphens.insert(Pango.attr_insert_hyphens_new(False))
        label.set_attributes(no_hyphens)
        label.add_css_class("monospace")
        copy_button = Gtk.Button(
            icon_name="edit-copy-symbolic", tooltip_text=_("Copy"),
            valign=Gtk.Align.START, margin_top=6, margin_end=6,
        )
        copy_button.add_css_class("flat")
        copy_button.connect("clicked", self._on_copy_commands, commands)
        commands_box = Gtk.Box(spacing=6)
        commands_box.add_css_class("card")
        commands_box.append(label)
        commands_box.append(copy_button)
        after_label = Gtk.Label(label=after, wrap=True, xalign=0)
        after_label.add_css_class("dimmed")
        extra = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        extra.append(commands_box)
        extra.append(after_label)
        dialog.set_extra_child(extra)

        dialog.add_response("notes", _("What's new"))
        dialog.add_response("later", _("Not now"))
        dialog.add_response("close", _("Close"))
        dialog.set_default_response("close")
        dialog.set_close_response("close")
        dialog.connect("response", self._on_update_response, release.url)
        dialog.present(self)

    def _on_copy_commands(self, button: Gtk.Button, commands: str) -> None:
        self.get_clipboard().set_content(Gdk.ContentProvider.new_for_value(commands))
        button.set_icon_name("object-select-symbolic")  # shows it worked

    def _on_update_response(self, _dialog, response: str, url: str) -> None:
        if response == "notes":
            Gtk.UriLauncher(uri=url).launch(self, None, None)
        elif response == "later" and self._update is not None:
            version = self._update.version
            self._update = None
            self._refresh()
            self._ask_about_next_updates(version)

    def _ask_about_next_updates(self, version: str) -> None:
        """After "not now": skip only this version, or stop checking altogether."""
        dialog = Adw.AlertDialog(heading=_("Let you know about the next versions?"))
        dialog.add_response("never", _("No, don't ask again"))
        dialog.add_response("yes", _("Yes, let me know"))
        dialog.set_response_appearance("yes", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("yes")
        dialog.set_close_response("yes")  # closing it only skips this version
        dialog.connect("response", self._on_next_updates_response, version)
        dialog.present(self)

    def _on_next_updates_response(self, _dialog, response: str, version: str) -> None:
        try:
            if response == "never":
                gnome.set_update_check_enabled(False)
            else:
                gnome.skip_update(version)
        except OSError as failure:
            self._toast(str(failure))

    def _show_about(self) -> None:
        dialog = _about_dialog()
        if not gnome.update_check_enabled():
            # The only way back for someone who said "don't ask again".
            dialog.add_link(_("Turn update notifications back on"), UPDATES_ON_LINK)
        dialog.connect("activate-link", self._on_about_link)
        dialog.present(self)

    def _on_about_link(self, dialog: Adw.AboutDialog, uri: str) -> bool:
        if uri != UPDATES_ON_LINK:
            return False  # a web link, opened as usual
        try:
            gnome.set_update_check_enabled(True)
        except OSError as failure:
            self._toast(str(failure))
            return True
        dialog.close()
        self._toast(_("Update notifications are on again"))
        self._check_for_update()
        return True

    def _build_skins(self) -> Gtk.Box:
        """Search and the add buttons, then a line with the number of skins."""
        self._search = Gtk.SearchEntry(placeholder_text=_("Search skins"), hexpand=True)
        self._search.connect("search-changed", lambda _entry: self._apply_search())
        open_button = Gtk.Button(
            child=Adw.ButtonContent(icon_name="list-add-symbolic", label=".osk"),
            tooltip_text=_("A skin packed in one file, like an .osk you downloaded or exported"),
        )
        open_button.add_css_class("suggested-action")
        open_button.connect("clicked", self._on_open)
        folder_button = Gtk.Button(
            child=Adw.ButtonContent(icon_name="list-add-symbolic", label=_("Folder")),
            tooltip_text=_("An unpacked skin folder, like a skin in osu! stable's Skins folder"),
        )
        folder_button.connect("clicked", self._on_open_folder)
        bar = Gtk.Box(spacing=8)
        for widget in (self._search, open_button, folder_button):
            bar.append(widget)

        self._library_label = Gtk.Label(xalign=0, hexpand=True)
        hint = Gtk.Label(label=DROP_HINT, ellipsize=Pango.EllipsizeMode.END)
        info = Gtk.Image(icon_name="dialog-information-symbolic", tooltip_text=_storage_note())
        line = Gtk.Box(spacing=6, margin_start=2)
        for widget in (self._library_label, hint, info):
            widget.add_css_class("dimmed")
            line.append(widget)
        for label in (self._library_label, hint):
            label.add_css_class("caption")

        self._skins = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._skins.append(bar)
        self._skins.append(line)
        return self._skins

    def _build_skin_list(self) -> Gtk.Stack:
        self._skin_list = Gtk.FlowBox(
            homogeneous=True,
            min_children_per_line=2,
            max_children_per_line=2,
            column_spacing=10,
            row_spacing=10,
            selection_mode=Gtk.SelectionMode.NONE,
            activate_on_single_click=True,
            valign=Gtk.Align.START,
            margin_bottom=PAGE_MARGIN,
        )
        self._skin_list.add_css_class("skin-cards")
        self._skin_list.connect("child-activated", self._on_skin_activated)

        menu = Gio.Menu()
        menu.append(_("Rename"), "win.rename-skin")
        menu.append(_("Open its folder"), "win.open-skin")
        menu.append(_("Remove"), "win.remove-skin")
        self._skin_menu = Gtk.PopoverMenu.new_from_model(menu)
        self._skin_menu.set_has_arrow(False)
        self._skin_menu.set_halign(Gtk.Align.START)
        self._skin_menu.set_parent(self._skin_list)
        for name, callback in (
            ("rename-skin", self._on_rename_skin),
            ("open-skin", self._on_open_skin),
            ("remove-skin", lambda _action, _parameter: self._menu_skin and self._on_remove_clicked(None, self._menu_skin)),
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
            vexpand=True,
        )
        self._skin_scroller.add_css_class("skin-scroller")
        # The scrollbar is hidden without its visible property changing, so whether
        # the cards overflow is what tells if it is there.
        self._skin_scroller.get_vadjustment().connect("changed", self._on_list_size_changed)
        self._fit_list_to_scrollbar()

        self._empty_label = Gtk.Label(label=EMPTY_HINT, wrap=True, justify=Gtk.Justification.CENTER,
                                      max_width_chars=36)
        self._empty_label.add_css_class("dimmed")
        self._skin_pages = Gtk.Stack(vexpand=True)
        self._skin_pages.add_named(self._skin_scroller, "cards")
        self._skin_pages.add_named(self._build_no_match(), "no-match")
        self._skin_pages.add_named(self._centred(self._empty_label), "empty")
        self._skin_pages.set_visible_child_name("empty")
        return self._skin_pages

    @staticmethod
    def _centred(widget: Gtk.Widget) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER,
                      margin_end=PAGE_MARGIN, margin_bottom=PAGE_MARGIN * 2)
        box.append(widget)
        return box

    def _on_list_size_changed(self, _adjustment) -> None:
        # Margins can't change while GTK is laying the window out.
        GLib.idle_add(self._fit_list_to_scrollbar)

    def _fit_list_to_scrollbar(self) -> bool:
        """Keep the cards' right edge where the parts above end, with or without a scrollbar.

        With overlay scrollbars turned off the scrollbar takes room of its own. It is made
        as wide as the page margin and moved into it, see _add_style.
        """
        adjustment = self._skin_scroller.get_vadjustment()
        overlay = (self._skin_scroller.get_overlay_scrolling()
                   and Gtk.Settings.get_default().get_property("gtk-overlay-scrolling"))
        shown = adjustment.get_upper() > adjustment.get_page_size() and not overlay
        margin = 0 if shown else PAGE_MARGIN
        if self._skin_list.get_margin_end() != margin:
            self._skin_list.set_margin_end(margin)
        return GLib.SOURCE_REMOVE

    def _build_no_match(self) -> Gtk.Box:
        """Shown in place of the cards when the search hides every skin."""
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=6,
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.CENTER,
            margin_end=PAGE_MARGIN,
            margin_bottom=PAGE_MARGIN * 2,
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

    def _build_reset(self) -> Gtk.Box:
        self._reset_button = Gtk.Button(
            child=Adw.ButtonContent(icon_name="edit-undo-symbolic", label=_("Go back to the previous cursor")),
        )
        self._reset_button.add_css_class("flat")
        self._reset_button.connect("clicked", self._on_reset)
        version = Gtk.Label(label=f"v{__version__}", hexpand=True, xalign=1)
        version.add_css_class("dimmed")
        footer = Gtk.Box(spacing=6)
        footer.add_css_class("footer")
        footer.append(self._reset_button)
        footer.append(version)
        return footer

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
        # One by one: remove_all() would also try to take away the right-click menu.
        for child, _text in self._skin_rows:
            self._skin_list.remove(child)
        self._skin_rows.clear()
        self._skin_checks.clear()
        self._row_skins.clear()

        for skin in skins:
            child = Gtk.FlowBoxChild(child=self._skin_card(skin))
            self._skin_list.append(child)
            self._skin_rows.append((child, _searchable(f"{skin.name} {skin.author}")))
            self._row_skins[child] = skin
        self._apply_search()
        self._refresh()
        self._reveal_pending()
        return GLib.SOURCE_REMOVE

    def _reveal_pending(self) -> None:
        """Scroll to the card of the skin just added and make it stand out for a moment.

        New skins are sorted in by name, so they can land far from where one is looking.
        """
        key, self._reveal_key = self._reveal_key, None
        card = next((card for card_key, _check, card in self._skin_checks if card_key == key), None)
        if card is None:
            return
        child = card.get_parent()
        if not child.get_visible():
            self._search.set_text("")  # the search hid it
            self._apply_search()
        child.grab_focus()
        # After the cards are laid out, so the new one has its place.
        GLib.idle_add(self._scroll_to, child)

        if self._highlight is not None:  # a newer highlight takes the place of the last one
            old_card, timer = self._highlight
            GLib.source_remove(timer)
            old_card.remove_css_class("just-added")
        card.add_css_class("just-added")
        self._highlight = (card, GLib.timeout_add(HIGHLIGHT_MS, self._end_highlight))

    def _end_highlight(self) -> bool:
        if self._highlight is not None:
            self._highlight[0].remove_css_class("just-added")
            self._highlight = None
        return GLib.SOURCE_REMOVE

    def _scroll_to(self, child: Gtk.FlowBoxChild) -> bool:
        """Bring a card fully into view, moving the list as little as needed."""
        found, bounds = child.compute_bounds(self._skin_list)
        if not found:
            return GLib.SOURCE_REMOVE
        adjustment = self._skin_scroller.get_vadjustment()
        top, bottom = bounds.get_y(), bounds.get_y() + bounds.get_height()
        if top < adjustment.get_value():
            adjustment.set_value(top)
        elif bottom > adjustment.get_value() + adjustment.get_page_size():
            adjustment.set_value(bottom - adjustment.get_page_size())
        return GLib.SOURCE_REMOVE

    def _skin_card(self, skin: gnome.LibrarySkin) -> Gtk.Box:
        """The cursor on a dark strip, with the name and the author under it, like osu!lazer."""
        texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(skin.preview_png))
        stage = Gtk.Box(height_request=STAGE_HEIGHT)
        stage.add_css_class("stage")
        stage.append(_Preview(texture))

        check = Gtk.Image(icon_name="object-select-symbolic", visible=False,
                          halign=Gtk.Align.END, valign=Gtk.Align.START, margin_top=8, margin_end=8)
        check.add_css_class("current-mark")
        remove_button = Gtk.Button(
            icon_name="user-trash-symbolic",
            tooltip_text=_("Remove from the list"),
            halign=Gtk.Align.START,
            valign=Gtk.Align.START,
            margin_top=6,
            margin_start=6,
        )
        remove_button.add_css_class("card-remove")
        remove_button.connect("clicked", self._on_remove_clicked, skin)
        top = Gtk.Overlay(child=stage)
        top.add_overlay(check)
        top.add_overlay(remove_button)

        name = Gtk.Label(label=skin.name, xalign=0, ellipsize=Pango.EllipsizeMode.END)
        name.add_css_class("skin-name")
        # An empty author keeps its line, so every card is as tall.
        author = Gtk.Label(label=skin.author or " ", xalign=0, ellipsize=Pango.EllipsizeMode.END)
        author.add_css_class("dimmed")
        author.add_css_class("caption")
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1,
                       margin_top=8, margin_bottom=9, margin_start=11, margin_end=11)
        text.append(name)
        text.append(author)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, overflow=Gtk.Overflow.HIDDEN,
                       tooltip_text=f"{skin.name}\n{skin.author}" if skin.author else skin.name)
        card.add_css_class("skin-card")
        card.append(top)
        card.append(text)
        self._skin_checks.append((skin.key, check, card))
        return card

    def _apply_search(self) -> None:
        query = _searchable(self._search.get_text())
        found = False
        for child, text in self._skin_rows:
            matches = query in text
            child.set_visible(matches)
            found = found or matches
        self._library_label.set_label(_("Library · {count}").format(count=len(self._skin_rows)))
        if not self._skin_rows:
            self._skin_pages.set_visible_child_name("empty")
        elif not found:
            self._no_match_query.set_label(
                _("Nothing found for “{query}”").format(query=self._search.get_text().strip())
            )
            self._skin_pages.set_visible_child_name("no-match")
        else:
            self._skin_pages.set_visible_child_name("cards")

    def _refresh(self) -> None:
        skin = gnome.current_skin()

        problem = gnome.desktop_notice() or gnome.trail_problem()
        self._banner.set_title(problem or "")
        self._banner.set_revealed(problem is not None)
        # A problem comes first, the new version waits until it is solved.
        update_shown = self._update is not None and problem is None
        if update_shown:
            self._update_banner.set_title(
                _("Version {version} is out").format(version=self._update.version)
            )
        self._update_banner.set_revealed(update_shown)

        self._reset_button.set_sensitive(skin is not None and not self._busy)
        current = gnome.current_skin_key()
        for key, check, card in self._skin_checks:
            check.set_visible(key == current)
            if key == current:
                card.add_css_class("current")
            else:
                card.remove_css_class("current")

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

    def _on_skin_activated(self, _cards, child: Gtk.FlowBoxChild) -> None:
        skin = self._row_skins.get(child)
        if skin is not None:
            self._apply(str(skin.path))

    def _build_drop_zone(self) -> Gtk.Revealer:
        icon = Gtk.Image(icon_name="folder-download-symbolic", pixel_size=48)
        title = Gtk.Label(label=_("Drop .osk files and skin folders here"), wrap=True,
                          justify=Gtk.Justification.CENTER)
        title.add_css_class("title-3")
        subtitle = Gtk.Label(label=_("They are added to the library"))
        subtitle.add_css_class("dimmed")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                      halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        for widget in (icon, title, subtitle):
            box.append(widget)
        zone = Gtk.Box(margin_bottom=PAGE_MARGIN, margin_end=PAGE_MARGIN)
        zone.add_css_class("drop-zone")
        zone.append(box)
        box.set_hexpand(True)
        # Not a target itself, the drop has to reach the window under it.
        return Gtk.Revealer(child=zone, can_target=False, reveal_child=False,
                            transition_type=Gtk.RevealerTransitionType.CROSSFADE,
                            transition_duration=120)

    def _on_drag_enter(self, _target, _x, _y) -> Gdk.DragAction:
        self._drop_zone.set_reveal_child(True)
        return Gdk.DragAction.COPY

    def _on_drop(self, _target, value, _x, _y) -> bool:
        self._drop_zone.set_reveal_child(False)
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
        skin = self._row_skins.get(self._skin_list.get_child_at_pos(int(x), int(y)))
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
            ).format(name=skin.name)
            # People worry the .osk or folder they chose goes too, it doesn't.
            + "\n\n" + _("The original file or folder you added it from is not deleted."),
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

    def _on_trail_toggled(self, switch, _param) -> None:
        try:
            gnome.set_trail_enabled(switch.get_active())
        except OSError as failure:
            self._toast(str(failure))
        self._refresh()

    def _on_size_changed(self, _scale) -> None:
        # The cursor follows the slider while it is dragged, at most once per interval.
        # Values that come in meanwhile collapse into the newest.
        self._show_size()
        self._pending_size = round(self._size_scale.get_value(), 2)
        if not self._size_timer:
            self._size_tick()

    def _size_tick(self) -> bool:
        self._size_timer = 0
        if self._pending_size is not None:
            self._run_pending_size()
            self._size_timer = GLib.timeout_add(SIZE_INTERVAL_MS, self._size_tick)
        return GLib.SOURCE_REMOVE

    def _run_pending_size(self) -> None:
        if self._busy or self._pending_size is None:
            return
        size, self._pending_size = self._pending_size, None
        # The rest of the window stays as it is, it would flicker while the slider moves.
        self._run(lambda: gnome.set_cursor_size(size), None, dim=False)

    def _set_busy(self, busy: bool, dim: bool = True) -> None:
        self._busy = busy
        if self._busy_timer:
            GLib.source_remove(self._busy_timer)
            self._busy_timer = 0
        if busy and dim:
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
        self._trail_switch.set_sensitive(sensitive)
        self._system_row.set_sensitive(sensitive)
        if not sensitive:
            self._reset_button.set_sensitive(False)

    def _is_free(self) -> bool:
        if self._busy:
            self._toast(_("The previous task is still running, wait a moment."))
        return not self._busy

    def _add(self, path: str) -> None:
        if not self._is_free():
            return

        def job() -> None:
            # Known before adding, so the card is found also when the skin was already there.
            self._reveal_key = gnome.skin_key(path)
            gnome.add_skin(path)

        self._run(job, _("Skin added to the list"), self._load_skins)

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
        dim: bool = True,
    ) -> None:
        self._set_busy(True, dim)

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
        if self._reveal_key is not None and (error or after_success is None):
            self._reveal_pending()  # "already in the list": show where it is
        if not self._size_timer:  # otherwise the next interval tick picks it up
            self._run_pending_size()
        if self._pending_apply is not None and not self._busy:
            path, self._pending_apply = self._pending_apply, None
            self._apply(path)
        return GLib.SOURCE_REMOVE

    def _on_reset(self, _button) -> None:
        if self._is_free():
            self._run(gnome.reset, _("Back to the previous cursor"))


def _about_dialog() -> Adw.AboutDialog:
    dialog = Adw.AboutDialog(
        application_name="Cursor for osu!",
        application_icon=APP_ID,
        version=__version__,
        developer_name="Egehan Kara",
        comments=_("Use the cursor and cursor trail of your osu! skins on GNOME or KDE Plasma, outside the game.")
        + "\n\n"
        + _("Cursor for osu! is a fan-made tool. It is not made by or affiliated with ppy or osu!."),
        website=update.REPOSITORY,
        issue_url=f"{update.REPOSITORY}/issues",
        license_type=Gtk.License.MIT_X11,
        copyright="© 2026 Egehan Kara",
    )
    # Our own heading, libadwaita's Turkish "Kodlayan" for developers reads oddly.
    dialog.add_credit_section(_("Developed by"), ["Egehan Kara https://github.com/egehankara"])
    dialog.add_credit_section(_("KDE Plasma support"), ["MehmetAkifUgur https://github.com/MehmetAkifUgur"])
    dialog.add_legal_section(
        "osu!",
        _("The cursor sizing and the trail are adapted from osu!.") + "\n© ppy Pty Ltd",
        Gtk.License.MIT_X11,
        None,
    )
    return dialog


def run() -> int:
    application = Adw.Application(application_id=APP_ID)
    application.connect("startup", _add_style)
    application.connect("activate", _present)
    return application.run(sys.argv[:1])


def _palette_css() -> str:
    """Recolour libadwaita itself, so dialogs, switches and buttons follow the palette."""
    colours = {
        "window-bg": "bg", "window-fg": "fg", "view-bg": "bg", "view-fg": "fg",
        "headerbar-bg": "bg", "headerbar-fg": "fg", "headerbar-backdrop": "bg",
        "headerbar-shade": "line", "headerbar-border": "line",
        "card-bg": "panel", "card-fg": "fg", "card-shade": "line",
        "dialog-bg": "panel", "dialog-fg": "fg", "popover-bg": "raised", "popover-fg": "fg",
        "thumbnail-bg": "panel", "thumbnail-fg": "fg",
        "accent-bg": "accent", "accent-fg": "accent-ink", "accent": "accent-text",
    }
    if (Adw.get_major_version(), Adw.get_minor_version()) >= (1, 6):
        lines = "".join(f"--{name}-color: {PALETTE[key]};" for name, key in colours.items())
        return f":root {{ {lines} }}"
    # Older libadwaita names its colours instead.
    return "".join(f"@define-color {name.replace('-', '_')}_color {PALETTE[key]};"
                   for name, key in colours.items())


def _add_style(_application: Adw.Application) -> None:
    Gtk.Window.set_default_icon_name(APP_ID)  # installed by install.sh, named after the app
    # The palette is dark, the dialogs and menus have to be dark as well.
    Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
    c = PALETTE
    scrollbar = PAGE_MARGIN
    css = Gtk.CssProvider()
    css.load_from_string(_palette_css() + f"""
        .controls {{ background: {c['panel']}; border: 1px solid {c['line']}; border-radius: 10px; }}
        .controls-line {{ padding: 8px 14px; }}
        scale.size trough {{ min-height: 3px; background: {c['line-strong']}; }}
        scale.size highlight {{ background: {c['accent']}; }}
        scale.size slider {{ min-width: 14px; min-height: 14px; margin: -6px; background: {c['fg']};
                             box-shadow: 0 0 0 3px {c['panel']}; }}
        entry.size-entry {{ background: none; min-height: 28px; padding: 0 6px; border-radius: 6px;
                            box-shadow: none; outline: none; }}
        entry.size-entry:hover {{ background: alpha({c['fg']}, 0.06); }}
        entry.size-entry:focus-within {{ background: {c['stage']}; box-shadow: inset 0 0 0 1px {c['accent']}; }}
        .more-settings {{ background: none; border-top: 1px solid {c['line']}; }}
        .more-settings > row {{ background: none; }}
        .more-settings > row:not(:last-child) {{ border-bottom: 1px solid {c['line']}; }}
        .skin-cards > flowboxchild {{ padding: 0; border-radius: 10px; background: none; }}
        .skin-card {{ background: {c['panel']}; border: 1px solid {c['line']}; border-radius: 10px; }}
        .skin-cards > flowboxchild:hover .skin-card {{ border-color: {c['line-strong']}; }}
        .skin-card.current, .skin-cards > flowboxchild:hover .skin-card.current {{
            border-color: {c['accent']}; box-shadow: inset 0 0 0 1px {c['accent']}; }}
        .stage {{ background-color: {c['stage']};
                  background-image: radial-gradient(circle, alpha(white, 0.045) 1px, transparent 1.5px);
                  background-size: 12px 12px; border-bottom: 1px solid {c['line']}; }}
        .skin-name {{ font-weight: 600; }}
        .current-mark {{ background: {c['accent']}; color: {c['accent-ink']}; border-radius: 999px;
                         min-width: 20px; min-height: 20px; -gtk-icon-size: 12px; }}
        .card-remove {{ opacity: 0; min-width: 28px; min-height: 28px; padding: 0; border-radius: 7px;
                        background: alpha({c['stage']}, 0.85); transition: opacity 120ms; }}
        .skin-cards > flowboxchild:hover .card-remove,
        .skin-cards > flowboxchild:focus-within .card-remove {{ opacity: 1; }}
        .card-remove:hover {{ background: #c01c28; color: white; }}
        /* A short flash, unlike the pink frame of the skin in use. */
        .skin-card {{ transition: background-color 500ms ease-out; }}
        .skin-card.just-added {{ background-color: alpha({c['accent']}, 0.22); transition: none; }}
        .footer {{ padding: 6px 10px; border-top: 1px solid {c['line']}; }}
        /* Our own drop zone instead of GTK's frame, which the header bar cut off. */
        .drop-target:drop(active) {{ box-shadow: none; outline: none; }}
        .drop-zone {{ background: alpha({c['bg']}, 0.92); border: 2px dashed {c['accent']};
                      border-radius: 14px; }}
        .drop-zone image {{ color: {c['accent']}; }}
        /* As wide as the page margin, so it fits in it next to the skin cards. */
        .skin-scroller > scrollbar.vertical, .skin-scroller > scrollbar.vertical > range,
        .skin-scroller > scrollbar.vertical trough {{ padding: 0; margin: 0; border: 0; min-width: 0; }}
        .skin-scroller > scrollbar.vertical slider {{ min-width: 6px; border: 0;
                                                      margin: 0 {(scrollbar - 6) // 2}px; }}
    """)
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )


def _present(application: Adw.Application) -> None:
    window = application.get_active_window() or Window(application)
    window.present()
