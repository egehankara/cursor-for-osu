"""A small window that accepts a dropped .osk file and sets the cursor size."""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import gnome  # noqa: E402
from .skin import SkinError  # noqa: E402

APP_ID = "io.github.xrayzack1010.OsuCursor"
DROP_TITLE = ".osk dosyasını buraya bırak"
SIZE_SETTLE_MS = 300


class Window(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application):
        super().__init__(application=application, title="osu! Cursor")
        self.set_default_size(480, 640)
        self._busy = False
        self._pending_size: float | None = None
        self._size_timer = 0

        self._status = Adw.StatusPage(icon_name="input-mouse-symbolic", title=DROP_TITLE)

        self._open_button = Gtk.Button(label="Dosya seç", halign=Gtk.Align.CENTER)
        self._open_button.add_css_class("pill")
        self._open_button.add_css_class("suggested-action")
        self._open_button.connect("clicked", self._on_open)

        self._reset_button = Gtk.Button(label="Önceki imlece dön", halign=Gtk.Align.CENTER)
        self._reset_button.add_css_class("pill")
        self._reset_button.connect("clicked", self._on_reset)

        size_label = Gtk.Label(label="Cursor boyutu", halign=Gtk.Align.START)
        size_label.add_css_class("heading")
        self._size_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, gnome.MIN_CURSOR_SIZE, gnome.MAX_CURSOR_SIZE, 0.01
        )
        self._size_scale.set_digits(2)
        self._size_scale.set_draw_value(True)
        self._size_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self._size_scale.set_size_request(320, -1)
        self._size_scale.add_mark(1.0, Gtk.PositionType.BOTTOM, None)
        self._size_scale.set_value(gnome.cursor_size())
        self._size_scale.connect("value-changed", self._on_size_changed)

        content_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER
        )
        content_box.append(size_label)
        content_box.append(self._size_scale)
        content_box.append(self._open_button)
        content_box.append(self._reset_button)
        self._status.set_child(content_box)

        self._toasts = Adw.ToastOverlay(child=self._status)
        content = Adw.ToolbarView(content=self._toasts)
        content.add_top_bar(Adw.HeaderBar())
        self.set_content(content)

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self._on_drop)
        self._status.add_controller(drop)

        self._refresh_description()

    def _refresh_description(self) -> None:
        skin = gnome.current_skin()
        description = f"Şu an: {GLib.markup_escape_text(skin)}" if skin else "Henüz skin uygulanmadı"
        problem = gnome.trail_problem()
        if problem:
            description += f"\n\n{GLib.markup_escape_text(problem)}"
        self._status.set_description(description)
        self._reset_button.set_sensitive(skin is not None and not self._busy)

    def _toast(self, text: str) -> None:
        self._toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text)))

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
        self._open_button.set_sensitive(not busy)
        if busy:
            self._reset_button.set_sensitive(False)

    def _apply(self, path: str) -> None:
        if self._busy:
            self._toast("Önceki işlem sürüyor, biraz bekle.")
            return
        self._status.set_title("Uygulanıyor…")
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
        self._status.set_title(DROP_TITLE)
        self._set_busy(False)
        self._refresh_description()
        if error:
            self._toast(error)
        elif success_message:
            self._toast(success_message)
        self._run_pending_size()
        return GLib.SOURCE_REMOVE

    def _on_reset(self, _button) -> None:
        try:
            gnome.reset()
        except Exception as failure:
            self._toast(str(failure))
            return
        self._refresh_description()
        self._toast("Önceki imlece dönüldü")


def run() -> int:
    application = Adw.Application(application_id=APP_ID)
    application.connect("activate", _present)
    return application.run(sys.argv[:1])


def _present(application: Adw.Application) -> None:
    window = application.get_active_window() or Window(application)
    window.present()
