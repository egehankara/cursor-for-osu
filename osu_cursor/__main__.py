"""Command line entry point. Without arguments it opens the window."""

from __future__ import annotations

import argparse
import os
import sys

from . import gnome
from .i18n import _
from .skin import SkinError


def _report(result: gnome.Result) -> None:
    print(_("Applied: {name} ({size} px)").format(name=result.skin_name, size=result.size_px))
    problem = gnome.trail_problem()
    if problem:
        print(problem)


def _uninstall(keep_data: bool) -> int:
    """Run the uninstall script that install.sh put next to the app."""
    script = gnome.data_dir() / "uninstall.sh"
    if not script.is_file():
        print(_("The uninstall script was not found. Run uninstall.sh from the source folder."), file=sys.stderr)
        return 1
    os.execvp("bash", ["bash", str(script), *(["--keep-data"] if keep_data else [])])


def main() -> int:
    parser = argparse.ArgumentParser(prog="cursor-for-osu")
    commands = parser.add_subparsers(dest="command")
    apply_parser = commands.add_parser("apply", help=_("apply a skin"))
    apply_parser.add_argument("skin", help=_(".osk file or skin folder"))
    apply_parser.add_argument(
        "--size",
        type=float,
        help=_("cursor size from 0.1 to 2.0 (default: the last one set, or your osu!lazer setting)"),
    )
    size_parser = commands.add_parser("size", help=_("change the cursor size"))
    size_parser.add_argument("value", type=float, help=_("from 0.1 to 2.0, like in the game"))
    commands.add_parser("reset", help=_("go back to the previous cursor"))
    commands.add_parser("status", help=_("show the applied skin"))
    uninstall_parser = commands.add_parser("uninstall", help=_("remove Cursor for osu! from this computer"))
    uninstall_parser.add_argument(
        "--keep-data", action="store_true", help=_("keep the skin list and settings")
    )
    arguments = parser.parse_args()

    if arguments.command is None:
        from .gui import run

        return run()
    if arguments.command == "uninstall":
        return _uninstall(arguments.keep_data)

    try:
        if arguments.command == "apply":
            _report(gnome.apply_skin(arguments.skin, arguments.size))
        elif arguments.command == "size":
            result = gnome.set_cursor_size(arguments.value)
            if result:
                _report(result)
            else:
                print(_("Size saved: {size}").format(size=f"{arguments.value:.2f}"))
        elif arguments.command == "reset":
            restored = gnome.reset()
            print(_("Back to: {theme}").format(theme=restored) if restored else _("Nothing to go back to."))
        else:
            print(_("Skin: {name}").format(name=gnome.current_skin() or _("none")))
            print(_("Size: {size}").format(size=f"{gnome.cursor_size():.2f}"))
            print(
                _("Trail extension: {state}").format(
                    state=_("on") if gnome.extension_active() else _("off")
                )
            )
    except SkinError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
