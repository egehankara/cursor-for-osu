"""The Windows skin library window."""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

from PySide6.QtCore import QEvent, QLockFile, QSignalBlocker, QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QScrollArea, QSlider,
    QStyle, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from . import library, windows
from .i18n import _
from .skin import SkinError
from .windows_trail import Trail


STYLE = """
QWidget { background: #191920; color: #f1edf5; font-size: 14px; }
QPushButton, QLineEdit { background: #2b2834; border: 1px solid #464052;
                         border-radius: 8px; padding: 8px 12px; }
QPushButton:hover { background: #44364a; }
QPushButton:focus, QLineEdit:focus { border: 2px solid #f0a0c6; }
QPushButton#skin { text-align: left; font-weight: 600; }
QPushButton#skin[active="true"] { border: 2px solid #f0a0c6; background: #483249; }
QPushButton:disabled, QLabel#hint { color: #c5bacb; }
QLabel#title { font-size: 23px; font-weight: 700; }
QSlider::groove:horizontal { background: #514458; height: 5px; border-radius: 2px; }
QSlider::handle:horizontal { background: #f0a0c6; width: 15px; margin: -5px 0;
                            border-radius: 7px; }
QScrollArea { border: none; }
"""


def label(text, name=None):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    if name:
        widget.setObjectName(name)
    return widget


class Window(QWidget):
    def __init__(self, application):
        super().__init__()
        self.setWindowTitle("Cursor for osu!")
        self.resize(680, 660)
        self.setMinimumSize(430, 470)
        self.setAcceptDrops(True)
        self.skin_list = []
        self.closing = False
        self.trail_signature = None
        self.active_key = None
        self.active_name = None
        page = QVBoxLayout(self)
        page.setContentsMargins(22, 20, 22, 20)
        page.setSpacing(12)
        page.addWidget(label("Cursor for osu!", "title"))

        size_row = QHBoxLayout()
        size_label = label(_("Cursor size"))
        self.size = QSlider(Qt.Orientation.Horizontal)
        self.size.setRange(10, 200)
        self.size.setValue(round(windows.cursor_size() * 100))
        self.size.setAccessibleName(size_label.text())
        self.size_text = label(f"{self.size.value() / 100:.2f}×")
        self.size.valueChanged.connect(self._size_changed)
        self.resize_timer = QTimer(self)
        self.resize_timer.setSingleShot(True)
        self.resize_timer.timeout.connect(self._save_size)
        size_row.addWidget(size_label)
        size_row.addWidget(self.size, 1)
        size_row.addWidget(self.size_text)
        page.addLayout(size_row)

        flags = QHBoxLayout()
        self.trail_box = QCheckBox(_("Trail"))
        self.trail_box.setChecked(windows.trail_enabled())
        self.trail_box.toggled.connect(lambda enabled: self._operation(windows.set_trail_enabled, enabled))
        flags.addWidget(self.trail_box)
        self.keep_box = QCheckBox(_("Keep system cursors"))
        self.keep_box.setChecked(windows.keep_system_cursors())
        self.keep_box.toggled.connect(lambda keep: self._operation(windows.set_keep_system_cursors, keep))
        flags.addWidget(self.keep_box)
        flags.addStretch()
        page.addLayout(flags)

        density_row = QHBoxLayout()
        density_label = label(_("Trail density"))
        self.density = QSlider(Qt.Orientation.Horizontal)
        self.density.setRange(windows.TRAIL_DENSITY_MIN, windows.TRAIL_DENSITY_MAX)
        self.density.setSingleStep(25)
        self.density.setPageStep(50)
        self.density.setTracking(False)
        self.density.setAccessibleName(density_label.text())
        self.density_text = label("")
        self.density.valueChanged.connect(lambda value: self._operation(windows.set_trail_density, value))
        self.density.sliderMoved.connect(lambda value: self.density_text.setText(f"{value}%"))
        density_row.addWidget(density_label)
        density_row.addWidget(self.density, 1)
        density_row.addWidget(self.density_text)
        page.addLayout(density_row)

        tools = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Search skins"))
        self.search.setAccessibleName(_("Search skins"))
        self.search.textChanged.connect(self._cards)
        tools.addWidget(self.search, 1)
        self._button(tools, ".osk", self._choose_files)
        self._button(tools, _("Folder"), self._choose_folder)
        page.addLayout(tools)
        self.scroller = QScrollArea()
        self.scroller.setWidgetResizable(True)
        page.addWidget(self.scroller, 1)
        self.status = label("", "hint")
        self.status.setWordWrap(True)
        page.addWidget(self.status)
        self._button(page, _("Go back to the previous cursor"), lambda: self._operation(windows.reset))
        self.trail = Trail(application, int(self.winId()), self._error, self._sync)
        self._reload()
        self._sync()
        self.tray_icon = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            icon = application.windowIcon()
            if icon.isNull():
                icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp)
            self.tray_icon = QSystemTrayIcon(icon, self)
            self.tray_icon.setToolTip(self.windowTitle())
            menu = QMenu(self)
            menu.addAction(_("Open Cursor for osu!"), self._show_window)
            menu.addAction(_("Quit Cursor for osu!"), application.quit)
            self.tray_icon.setContextMenu(menu)
            self.tray_icon.activated.connect(self._tray_activated)
            self.tray_icon.show()
        application.aboutToQuit.connect(self._shutdown)

    def _button(self, layout, title, callback):
        button = QPushButton(title)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def _error(self, error):
        self.status.setText(str(error) or _("unknown error"))

    def _operation(self, callback, *args, reload=False):
        try:
            result = callback(*args)
            self.status.setText("")
            if result is not None:
                self.status.setText(_("Applied: {name} ({size} px)").format(name=result.skin_name, size=result.size_px))
            if reload:
                self._reload()
        except (SkinError, OSError, RuntimeError, zipfile.BadZipFile) as error:
            self._error(error)
        self._sync()

    def _sync(self):
        if self.closing:
            return
        state = windows.active()
        trail_enabled = windows.trail_enabled()
        density = windows.trail_density()
        with QSignalBlocker(self.trail_box), QSignalBlocker(self.keep_box), QSignalBlocker(self.density):
            self.trail_box.setChecked(trail_enabled)
            self.keep_box.setChecked(windows.keep_system_cursors())
            self.density.setValue(density)
        self.density_text.setText(f"{density}%")
        key, name = state.get("key"), state.get("name")
        if (key, name) != (self.active_key, self.active_name):
            self.active_key, self.active_name = key, name
            self._cards()
        signature = (key, state.get("fingerprint"), state.get("scale"), trail_enabled, density)
        if signature != self.trail_signature:
            self.trail_signature = signature
            try:
                self.trail.configure(windows.trail_skin(state), state, windows.cursor_size(), density / 100)
            except (SkinError, OSError, RuntimeError, zipfile.BadZipFile) as error:
                self.trail.stop()
                self._error(error)

    def _size_changed(self, value):
        self.size_text.setText(f"{value / 100:.2f}×")
        self.resize_timer.start(180)

    def _save_size(self):
        self._operation(windows.set_cursor_size, self.size.value() / 100)

    def _reload(self):
        self.skin_list = library.library_skins()
        self._cards()

    def _cards(self):
        contents = QWidget()
        cards = QVBoxLayout(contents)
        cards.setContentsMargins(1, 1, 8, 1)
        cards.setSpacing(8)
        term = self.search.text().strip().casefold()
        visible = [skin for skin in self.skin_list if term in f"{skin.name} {skin.author}".casefold()]
        if not self.skin_list:
            hint = label(_("No skins yet. Choose an .osk file or a folder, or drop them on the window."), "hint")
            hint.setWordWrap(True)
            cards.addWidget(hint)
        for skin in visible:
            card = QFrame()
            row = QHBoxLayout(card)
            row.setContentsMargins(0, 0, 0, 0)
            selected = skin.key == self.active_key
            name = f"✓ {skin.name}" if selected else skin.name
            if skin.author:
                name += f"\n{skin.author}"
            button = self._button(row, name, lambda _checked=False, item=skin: self._operation(windows.apply_skin, item.path))
            button.setObjectName("skin")
            button.setProperty("active", selected)
            pixmap = QPixmap()
            pixmap.loadFromData(skin.preview_png)
            button.setIcon(QIcon(pixmap))
            button.setIconSize(QSize(144, 50) if skin.has_trail else QSize(50, 50))
            button.setMinimumHeight(65)
            menu = QMenu(card)
            menu.addAction(_("Rename"), lambda _checked=False, item=skin: self._rename(item))
            menu.addAction(_("Remove"), lambda _checked=False, item=skin: self._remove(item))
            more = self._button(row, "⋯", lambda _checked=False, m=menu: m.popup(self.cursor().pos()))
            more.setAccessibleName(skin.name)
            more.setFixedWidth(42)
            cards.addWidget(card)
        cards.addStretch()
        old = self.scroller.takeWidget()
        if old is not None:
            old.deleteLater()
        self.scroller.setWidget(contents)

    def _choose_files(self):
        paths, _filter = QFileDialog.getOpenFileNames(self, _("Choose a skin"), "", "osu! (*.osk)")
        self._import(paths)

    def _choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, _("Choose a skin folder"))
        if path:
            self._import([path])

    def _import(self, paths):
        if not paths:
            return
        try:
            if len(paths) == 1:
                library.add_skin(paths[0])
                self.status.setText(_("Skins added: {added}").format(added=1))
            else:
                added, skipped = library.add_skins(paths)
                self.status.setText(_("Skins added: {added}, skipped: {skipped}").format(added=added, skipped=skipped))
            self._reload()
        except (SkinError, OSError, RuntimeError, zipfile.BadZipFile) as error:
            self._error(error)

    def _rename(self, skin):
        name, ok = QInputDialog.getText(self, _("Rename the skin"), _("Rename"), text=skin.name)
        if ok:
            self._operation(windows.rename_skin, skin.path, name, reload=True)

    def _remove(self, skin):
        if QMessageBox.question(self, _("Remove the skin?"), skin.name) == QMessageBox.StandardButton.Yes:
            self._operation(windows.remove_skin, skin.path, reload=True)

    def dragEnterEvent(self, event):
        if any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        self._import([url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()])
        event.acceptProposedAction()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow() and hasattr(self, "trail"):
            self._sync()

    def _show_window(self):
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show_window()

    def _shutdown(self):
        if self.closing:
            return
        if self.resize_timer.isActive():
            self.resize_timer.stop()
            self._save_size()
        self.closing = True
        self.trail.close()
        if self.tray_icon is not None:
            self.tray_icon.hide()

    def closeEvent(self, event):
        if not self.closing and self.tray_icon is not None and self.tray_icon.isVisible():
            event.ignore()
            self.hide()
            return
        self._shutdown()
        super().closeEvent(event)


def run():
    application = QApplication(sys.argv[:1])
    application.setStyle("Fusion")
    application.setStyleSheet(STYLE)
    icon = Path(__file__).with_name("app.ico")
    if icon.is_file():
        application.setWindowIcon(QIcon(str(icon)))
    directory = library.data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(directory / "window.lock"))
    if not lock.tryLock(0):
        QMessageBox.information(None, "Cursor for osu!", _("The previous task is still running, wait a moment."))
        return 1
    window = Window(application)
    window.show()
    return application.exec()
